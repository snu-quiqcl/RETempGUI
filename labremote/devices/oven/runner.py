"""Cancellable loading workflow; all device I/O goes through queued operations."""
import time
from labremote.api.devices import DeviceAPI
from labremote.devices.ccd.worker import CCDAPI
from labremote.devices.ccd.detection import DetectionConfig, positive_int
from labremote.runtime.workflow_runner import WorkflowTask, _TASK_LOCK
from labremote.runtime.jobs import ExecutionHandle
from labremote.operation.oven_psu import control as power
from labremote.operation.oven_relay import control as relay
from .settings import PROFILES


class OvenLoadTask(WorkflowTask):
    timeout_s = 600.

    def __init__(self, psu, relays, ccd):
        super().__init__(psu, 'OVEN_LOAD')
        self.psu, self.relays, self.ccd = psu, relays, ccd
        self._deadline = None
        self._cleaning = False
        self.ccd.oven_runner = self
        self.flip_routing = None

    def start(self, isotope=171, *, shutter='shutter_2', shutter_confirmed=None,
              threshold=1000, min_area=3, target=1, consecutive_frames=3, roi=None, parent=None, follow_viewport=False):
        # shutter_confirmed is accepted only for compatibility with older workflows.
        with _TASK_LOCK:
            try:
                if self.running(): raise RuntimeError('Oven loading is already running or stopping')
                flip_plan=()
                if self.flip_routing is not None:
                    if self.flip_routing.task.running() or any(w.has_requests() for w in self.flip_routing.workers.values()):
                        raise RuntimeError('Finish flipper operations before oven loading')
                    flip_plan=self.flip_routing.plan('EC',automatic=True)
                if self.relays.has_requests():raise RuntimeError('Finish shutter operations before oven loading')
                if self.psu.io_fault or self.relays.io_fault:
                    raise ConnectionError('Recover the server device connection, then Connect oven devices again; live response verification is required')
                if type(isotope) is not int or isotope not in (171, 174): raise ValueError('Select 171 or 174')
                if shutter not in ('shutter_1', 'shutter_2'):
                    raise ValueError('Select shutter_1 or shutter_2')
                if not self.ccd.available: raise ConnectionError('Connect the CCD first')
                if getattr(self.ccd, 'backend_name', '') != 'Thorcam':
                    raise ValueError('Real oven loading requires Thorcam, not Dummy CCD')
                with self.ccd._handles_lock:
                    if self.ccd._handles: raise RuntimeError('Finish pending CCD operations/ion waits first')
                positive_int(consecutive_frames, 'Consecutive frames')
                DetectionConfig(threshold, min_area, target, roi).validate(self.ccd.sensor_shape)
            except Exception as exc:
                handle = ExecutionHandle('OVEN_LOAD', None, parent)
                if parent is not None: parent.add(handle)
                handle.finish(exc)
                self.worker.task_changed.emit(self.label, handle)
                return handle
            settings = dict(isotope=isotope, route=f'EC_{isotope}', shutter=shutter,
                            threshold=threshold, min_area=min_area, target=target,
                            consecutive_frames=consecutive_frames, roi=roi, follow_viewport=follow_viewport)
            settings['flip_plan']=flip_plan
            flips=tuple(self.flip_routing.workers[name] for name,_ in flip_plan)
            return self.launch(self._execute, (self.psu, self.relays,*flips), settings, parent)

    def check(self):
        super().check()
        if self._cleaning: return
        if not self.ccd.available or self.ccd._closing:
            raise ConnectionError('CCD disconnected during oven loading')
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise TimeoutError('Oven loading reached the 600-second timeout')

    def call(self, handle):
        try:
            while not handle.done.wait(.05):
                try: self.check()
                except Exception:
                    handle.request_cancel()
                    # Do not return while a write/readback is still in flight.
                    try: handle.wait()
                    except Exception: pass
                    raise
            return super().call(handle)
        finally:
            with self.group.lock:
                if handle in self.group.handles:self.group.handles.remove(handle)

    def _operation(self, worker, label, fn, *args, cleanup=False):
        api = DeviceAPI(worker, group=None if cleanup else self.group)
        handle = api._submit(label, lambda w: fn(w.ps, *args))
        return handle.wait() if cleanup else self.call(handle)

    def _execute(self):
        self._deadline = time.monotonic() + self.timeout_s
        self._cleaning = False
        s = self.settings
        voltage, current = PROFILES[s['route']]
        watch = None
        error = None
        result = None
        ramp_current = 0.
        try:
            self.publish(phase='PSU OFF / current verification', route=s['route'], timeout_s=self.timeout_s)
            self._operation(self.psu, 'OVEN_OFF', power.off)
            self._operation(self.relays, 'OVEN_SHUTTER_CLOSE', relay.close_shutter, s['shutter'])
            from labremote.operation.flip.control import move as flip_move
            for name,position in s['flip_plan']:
                self.check()
                self._operation(self.flip_routing.workers[name],'FLIP_ROUTE_MOVE',flip_move,position)
            ccd = CCDAPI(self.ccd, group=self.group)
            self.call(ccd.stop_acquisition())
            self.call(ccd.configure_detection(threshold=s['threshold'], min_area=s['min_area'], target=s['target'], roi=s['roi'], **({'follow_viewport': True} if s.get('follow_viewport') else {})))
            self.call(ccd.start_acquisition())
            self.publish(phase='Select EC oven / configure CH1', route=s['route'])
            self._operation(self.relays, 'OVEN_ROUTE', relay.select, s['route'])
            self._operation(self.psu, 'OVEN_CURRENT_SETUP', power.configure, voltage, current)
            self._operation(self.relays, 'OVEN_SHUTTER_OPEN', relay.open_shutter, s['shutter'], s['route'])
            self.check()
            self._operation(self.psu, 'OVEN_ON', power.on, voltage, current)
            self.publish(phase='Waiting for ions', voltage_limit_v=voltage, current_limit_a=current)
            remaining = max(.001, self._deadline-time.monotonic())
            watch = ccd.wait_for_ions(s['target'], consecutive_frames=s['consecutive_frames'], timeout_s=remaining)
            next_sample = 0
            next_step = 0
            while not watch.done.wait(.05):
                self.check()
                if ramp_current < current and time.monotonic() >= next_step:
                    # Record the attempted level before I/O so interrupted writes
                    # also have a conservative starting point for shutdown.
                    ramp_current = round(min(current, ramp_current + power.RAMP_STEP_A), 6)
                    self._operation(self.psu, 'OVEN_RAMP_UP', power.set_current, ramp_current)
                    self.publish(ramp_current_a=ramp_current)
                    next_step = time.monotonic() + power.RAMP_INTERVAL_S
                    if watch.done.is_set(): break
                if time.monotonic() >= next_sample:
                    sample = self._operation(self.psu, 'OVEN_READBACK', power.read_snapshot)
                    self.publish(**sample, remaining_s=max(0.,self._deadline-time.monotonic()))
                    if sample['output'] != 'ON': raise RuntimeError('Oven PSU output turned OFF unexpectedly')
                    if watch.done.is_set(): break
                    self._operation(self.relays, 'OVEN_ROUTE_CHECK', relay.verify_route, s['shutter'], s['route'])
                    next_sample = time.monotonic()+1.
            result = self.call(watch)
        except Exception as exc:
            error = exc
        finally:
            self._cleaning = True
            if watch is not None and not watch.done.is_set():watch.request_cancel()
            self.publish(phase='Stopping: current ramp down / PSU OFF / shutter CLOSED')
            failures = []
            # Independent, uncancelled operations: attempt BOTH even if one fails.
            for worker, label, fn, args in (
                (self.psu, 'OVEN_OFF', power.off if self.psu.io_fault else power.ramp_down,
                 () if self.psu.io_fault else (ramp_current,)),
                (self.relays, 'OVEN_SHUTTER_CLOSE', relay.close_shutter, (s['shutter'],))):
                try:self._operation(worker, label, fn, *args, cleanup=True)
                except Exception as exc:failures.append(f'{label}: {exc}')
            if watch is not None:
                try:watch.wait(6)
                except Exception:pass
                with self.group.lock:
                    if watch in self.group.handles:self.group.handles.remove(watch)
            if failures:
                self.publish(phase='OFF/CLOSE NOT CONFIRMED — check hardware', cleanup_confirmed=False)
                raise RuntimeError('Oven cleanup not confirmed. Check PSU/shutter manually. '+ '; '.join(failures) + (f'; original: {error}' if error else ''))
            self.publish(phase='PSU OFF / shutter CLOSED', cleanup_confirmed=True, output='OFF')
        if error is not None:raise error
        return {'ions': result, 'route': s['route'], 'cleanup_confirmed': True}
