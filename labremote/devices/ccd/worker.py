"""Qt-facing local command service; no GUI work and no instrumentserver transport."""
import multiprocessing as mp
import queue
import threading
import time
from types import SimpleNamespace
import numpy as np
from PyQt5 import QtCore
from labremote.runtime.jobs import ExecutionHandle
from labremote.runtime.errors import OperationCancelled
from .process import camera_process, HEADER_SIZE, MAX_MARKERS


class CCDWorker(QtCore.QThread):
    connected = QtCore.pyqtSignal(object)
    disconnected = QtCore.pyqtSignal(str)
    failure = QtCore.pyqtSignal(str, str)
    handle_changed = QtCore.pyqtSignal(object)
    state_changed = QtCore.pyqtSignal(object)
    family = 'ccd'

    def __init__(self, name='ccd_local'):
        super().__init__()
        self.name = name
        self.operation_bridge = SimpleNamespace(worker=self)
        self._background_tasks = set()
        self._closing = False
        self._queue = queue.Queue()
        self._handles = {}
        self._handles_lock = threading.Lock()
        self._preview_lock = threading.Lock()
        self._preview = None
        self.acquiring = False
        self.available = False
        self.backend_name = ''
        self.sensor_shape = (0, 0)
        self.connection_error = False
        self._process = None
        self._pipe = None
        self._shared = None
        self._shared_lock = None

    def submit(self, action, args=None, group=None):
        handle = ExecutionHandle('CCD_'+action.upper(), None, group)
        handle.arguments = dict(args or {})
        oven = getattr(self, 'oven_runner', None)
        if oven is not None and oven.running() and group is not oven.group and action not in ('stop', 'disconnect', 'save') and not (action == 'viewport' and getattr(oven, 'settings', {}).get('follow_viewport', False)):
            handle.finish(RuntimeError('CCD is reserved by oven loading; stop the oven task first'))
            return handle
        if group is not None: group.add(handle)
        with self._handles_lock:
            if self._closing:
                handle.finish(OperationCancelled('CCD worker is closing'))
                return handle
            self._handles[handle.request_id] = handle
        self._queue.put((handle, action))
        return handle

    def cancel_backgrounds(self):
        with self._handles_lock:
            for handle in self._handles.values(): handle.request_cancel()

    def shutdown(self):
        self._closing = True
        self.cancel_backgrounds()

    def latest_preview(self):
        with self._preview_lock: return self._preview

    def _finish(self, handle, value=None, error=None):
        if error is not None and handle.group is not None: handle.group.stop.set()
        handle.finish(error, result=value)
        with self._handles_lock: self._handles.pop(handle.request_id, None)
        self.handle_changed.emit(handle)
        if handle.error and not isinstance(handle.error, OperationCancelled):
            self.failure.emit(handle.action, str(handle.error))

    def _close_process(self, reason):
        self.acquiring = False
        self.available = False
        if self._process is not None:
            try:
                if self._process.is_alive():
                    self._pipe.send(('', 'shutdown', {}))
                    self._process.join(15)
                if self._process.is_alive():
                    self._process.terminate()
                    self._process.join(2)
                    self.failure.emit('CCD_SHUTDOWN', 'Camera process did not exit; forced termination. Check any pending save.')
                self._process.close()
            except (OSError, ValueError): pass
        if self._pipe is not None: self._pipe.close()
        self._process = self._pipe = self._shared = self._shared_lock = None
        with self._preview_lock: self._preview = None
        self.disconnected.emit(reason)

    def _connect(self, options):
        if self._process is not None: raise RuntimeError('Disconnect CCD before reconnecting')
        context = mp.get_context('spawn')
        self._shared = context.RawArray('B', HEADER_SIZE + 4096*4096*2)
        self._shared_lock = context.Lock()
        self._pipe, child = context.Pipe()
        self._process = context.Process(target=camera_process,
            args=(child, self._shared, self._shared_lock, options), name='CCD-local', daemon=True)
        self._process.start()
        child.close()

    def _read_preview(self):
        if self._shared is None or not self._shared_lock.acquire(False): return
        try:
            header = np.frombuffer(self._shared, dtype=np.int64, count=12).copy()
            seq, h, w = map(int, header[:3])
            if not seq or (self._preview is not None and self._preview['frame_id'] == seq): return
            image = np.frombuffer(self._shared, dtype=np.uint16, count=h*w, offset=HEADER_SIZE).reshape(h, w).copy()
            centers = np.frombuffer(self._shared, dtype=np.float32, count=min(int(header[4]), MAX_MARKERS)*2, offset=12*8).reshape(-1, 2).copy()
        finally: self._shared_lock.release()
        image.flags.writeable = False
        snapshot = dict(frame_id=seq, image=image, centers=centers, received_ns=int(header[3]), count=int(header[4]),
                        target=int(header[5]), raw_min=int(header[6]), raw_max=int(header[7]),
                        run_id=int(header[8]), acquired=int(header[9]), analyzed_ns=int(header[10]),
                        detection_revision=int(header[11]))
        with self._preview_lock: self._preview = snapshot

    def run(self):
        pending = {}
        next_preview = 0
        connect_handle = None
        try:
            while not self._closing:
                for _ in range(16):
                    try: handle, action = self._queue.get_nowait()
                    except queue.Empty: break
                    if handle.done.is_set(): continue
                    try:
                        handle.check_cancelled()
                        handle.status = 'running'
                        self.handle_changed.emit(handle)
                        if action == 'connect':
                            self._connect(handle.arguments)
                            connect_handle = handle
                            pending[handle.request_id] = (handle, time.monotonic()+20, action, False)
                        elif action == 'disconnect':
                            self._close_process('CCD disconnected')
                            for other, _, _, _ in pending.values():
                                self._finish(other, error=ConnectionError('CCD disconnected'))
                            pending.clear()
                            connect_handle = None
                            self._finish(handle)
                        else:
                            if not self.available: raise ConnectionError('Connect local CCD first')
                            budget = float(handle.arguments.get('timeout_s', 120 if action == 'save' else 20)) + 5
                            if action == 'capture' and handle.arguments.get('save_path'): budget += 120
                            self._pipe.send((handle.request_id, action, handle.arguments))
                            pending[handle.request_id] = (handle, time.monotonic()+budget, action, False)
                    except Exception as exc:
                        self._finish(handle, error=exc)
                if self._pipe is not None:
                    while self._pipe.poll():
                        msg = self._pipe.recv()
                        if msg[0] == 'ready':
                            self.available = True
                            self.backend_name = msg[1]['backend']
                            self.sensor_shape = tuple(msg[1]['shape'])
                            self.connection_error = False
                            self.connected.emit(msg[1])
                            if connect_handle:
                                pending.pop(connect_handle.request_id, None)
                                self._finish(connect_handle, msg[1])
                                connect_handle = None
                        elif msg[0] == 'reply':
                            _, request_id, value, error = msg
                            item = pending.pop(request_id, None)
                            if item:
                                handle, _, action, _ = item
                                exception = None
                                if error:
                                    cls = {'TimeoutError': TimeoutError, 'ValueError': ValueError,
                                           'OperationCancelled': OperationCancelled}.get(error[0], RuntimeError)
                                    exception = cls(error[1])
                                self._finish(handle, value, exception)
                                if exception is None and action in ('start', 'stop', 'capture'):
                                    self.acquiring = action == 'start'
                                    self.state_changed.emit({'running': self.acquiring})
                        elif msg[0] == 'state':
                            self.acquiring = bool(msg[1].get('running'))
                            self.state_changed.emit(msg[1])
                        elif msg[0] == 'fatal': raise ConnectionError(msg[1])
                    if not self._process.is_alive(): raise ConnectionError('CCD process exited')
                for request_id, (handle, deadline, action, cancel_sent) in list(pending.items()):
                    if time.monotonic() > deadline:
                        raise TimeoutError('CCD process response timed out: ' + action)
                    if handle.cancelled() and not cancel_sent:
                        if action == 'connect': raise OperationCancelled('CCD connection cancelled')
                        self._pipe.send(('', 'cancel', {'request_id': request_id}))
                        pending[request_id] = (handle, deadline, action, True)
                if time.monotonic() >= next_preview:
                    self._read_preview()
                    next_preview = time.monotonic() + .033
                self.msleep(2)
        except Exception as exc:
            self.connection_error = True
            for handle, _, _, _ in pending.values(): self._finish(handle, error=exc)
            self.failure.emit('CCD', str(exc))
        finally:
            self._close_process('CCD stopped')
            with self._handles_lock: outstanding = tuple(self._handles.values())
            for handle in outstanding:
                self._finish(handle, error=OperationCancelled('CCD worker stopped'))


class CCDAPI:
    def __init__(self, worker, channel=None, group=None):
        self.worker, self.group = worker, group

    def _submit(self, action, **args): return self.worker.submit(action, args, self.group)
    def connect(self, *, backend='Thorcam', serial='', dll_path='', dummy_ions=3):
        return self._submit('connect', backend=backend, serial=serial, dll_path=dll_path, dummy_ions=dummy_ions)
    def disconnect(self): return self._submit('disconnect')
    def configure(self, *, exposure_ms=None, gain=None):
        return self._submit('configure', exposure_ms=exposure_ms, gain=gain)
    def configure_detection(self, *, threshold=1000, min_area=3, target=1, roi=None, follow_viewport=False):
        return self._submit('detection', threshold=threshold, min_area=min_area, target=target, roi=roi, follow_viewport=follow_viewport)
    def update_viewport(self, roi): return self._submit('viewport', roi=roi)
    def start_acquisition(self): return self._submit('start')
    def stop_acquisition(self):
        # Cleanup remains possible after this workflow's cancellation or failure.
        return self.worker.submit('stop')
    def capture(self, frames=1, *, timeout_s=60, save_path=None):
        return self._submit('capture', frames=frames, timeout_s=timeout_s, save_path=save_path)
    def wait_for_ions(self, target=1, *, consecutive_frames=3, timeout_s=60):
        return self._submit('wait', target=target, consecutive_frames=consecutive_frames, timeout_s=timeout_s)
    def save(self, path, *, sequence=False, roi_only=False):
        return self._submit('save', path=str(path), sequence=sequence, roi_only=roi_only)
    def cancel(self): self.worker.cancel_backgrounds()

    def load_oven(self, isotope=171, *, shutter='shutter_2', shutter_confirmed=None,
                  threshold=1000, min_area=3, target=1, consecutive_frames=3, roi=None):
        runner = getattr(self.worker, 'oven_runner', None)
        if runner is None: raise RuntimeError('Use the CCD panel oven connections first')
        return runner.start(isotope, shutter=shutter, shutter_confirmed=shutter_confirmed,
                            threshold=threshold, min_area=min_area, target=target,
                            consecutive_frames=consecutive_frames, roi=roi, parent=self.group)

    def stop_oven(self):
        runner = getattr(self.worker, 'oven_runner', None)
        if runner is None: raise RuntimeError('No oven loader attached')
        return runner.cancel()
