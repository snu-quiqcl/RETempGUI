"""Single SDK owner process. Frames never travel through the command Pipe."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
import time
import numpy as np
from .detection import DetectionConfig, detect_ions, crop, positive_int, positive_seconds

MAX_MARKERS = 1024
HEADER_SIZE = 12 * 8 + MAX_MARKERS * 2 * 4


def save_frames(path, frames, roi=None):
    """A bounded writer owns immutable frame references until durable completion."""
    from PIL import Image
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() not in ('.tif', '.tiff', '.png'):
        raise ValueError('Choose .tif, .tiff or .png')
    if not frames: raise ValueError('No frames to save')
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = [crop(frame, roi) for frame in frames]
    if path.suffix.lower() == '.png':
        if len(arrays) != 1: raise ValueError('PNG saves one frame; use TIFF for a sequence')
        # Keep quantitative unsigned pixel values; display levels never alter saved data.
    images = [Image.fromarray(arr) for arr in arrays]
    try:
        # Exclusive creation: never silently overwrite an earlier experiment.
        with path.open('x+b') as stream:
            if path.suffix.lower() == '.png': images[0].save(stream, format='PNG')
            else: images[0].save(stream, format='TIFF', save_all=True, append_images=images[1:])
    finally:
        for image in images: image.close()
    return {'path': str(path), 'frames': len(frames)}


def camera_process(pipe, shared, lock, options):
    """All SDK calls are serialized here, including stop and configuration.

    Preview is a single bounded shared-memory slot. Detection runs on every
    received frame and evaluates waits here, regardless of UI polling speed.
    """
    from .backends import DummyCamera, ThorCamera
    camera = None
    writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ccd-save')
    saves = {}
    waits = {}
    capture_id = None
    running = False
    frames = deque()
    frame_id = 0
    run_id = 0
    acquired = 0
    last_device_id = None
    detection = DetectionConfig()
    follow_viewport = False
    viewport_empty = False
    detection_revision = 0
    detection_changed_ns = time.perf_counter_ns()
    header = np.frombuffer(shared, dtype=np.int64, count=12)
    markers = np.frombuffer(shared, dtype=np.float32, count=MAX_MARKERS*2, offset=12*8).reshape(-1, 2)
    pixels = np.frombuffer(shared, dtype=np.uint16, offset=HEADER_SIZE)

    def reply(request_id, value=None, error=None):
        pipe.send(('reply', request_id, value, error))

    def fail_waits(message, kind='RuntimeError'):
        for request_id in list(waits): reply(request_id, error=(kind, message))
        waits.clear()

    def stop(reason='Acquisition stopped'):
        nonlocal running, capture_id
        camera.stop()
        running = False
        fail_waits(reason)
        if capture_id is not None:
            reply(capture_id, error=('RuntimeError', reason))
            capture_id = None

    try:
        import cv2
        cv2.setNumThreads(1)  # Do not oversubscribe the host's other device workers.
        backend = options.get('backend', 'Thorcam')
        if backend not in ('Thorcam', 'Dummy'): raise ValueError('Unknown CCD backend')
        camera = (DummyCamera if backend == 'Dummy' else ThorCamera)(options)
        h, w = camera.shape
        if h*w > pixels.size: raise ValueError('Sensor exceeds configured preview memory capacity')
        max_frames = min(50, max(1, 256*1024*1024 // (h*w*2)))
        frames = deque(maxlen=max_frames)
        detection.validate(camera.shape)
        pipe.send(('ready', {'shape': camera.shape, 'exposure_ms': camera.exposure_ms,
                             'gain': camera.gain, 'max_frames': max_frames, 'backend': backend}))
        alive = True
        while alive:
            # Limit each command batch so acquisition cannot be starved by UI commands.
            for _ in range(16):
                if not pipe.poll(): break
                request_id, command, args = pipe.recv()
                try:
                    if command == 'shutdown':
                        alive = False
                        break
                    if command == 'cancel':
                        target = args['request_id']
                        if target in waits:
                            waits.pop(target)
                            reply(target, error=('OperationCancelled', 'CCD wait cancelled'))
                        elif target == capture_id:
                            request, capture_id = capture_id, None
                            stop('CCD capture cancelled')
                            reply(request, error=('OperationCancelled', 'CCD capture cancelled'))
                        # Saving is allowed to finish; parent marks the handle cancelled.
                        continue
                    if command == 'configure':
                        if running: raise RuntimeError('Stop acquisition before changing exposure or gain')
                        exposure, gain = args.get('exposure_ms'), args.get('gain')
                        if exposure is not None: positive_seconds(exposure)
                        if gain is not None and (type(gain) is not int or gain < 0):
                            raise ValueError('Gain must be a nonnegative integer')
                        camera.configure(exposure, gain)
                        reply(request_id, {'exposure_ms': camera.exposure_ms, 'gain': camera.gain})
                    elif command == 'detection':
                        if waits: raise RuntimeError('Cancel active ion waits before changing detection settings')
                        config_args = {k:v for k,v in args.items() if k!='follow_viewport'}
                        updated = DetectionConfig(**config_args).validate(camera.shape)
                        follow_viewport = bool(args.get('follow_viewport', False))
                        viewport_empty = False
                        detection = updated
                        detection_revision += 1
                        detection_changed_ns = time.perf_counter_ns()
                        reply(request_id, {**asdict(detection), 'follow_viewport': follow_viewport})
                    elif command == 'viewport':
                        if not follow_viewport:
                            reply(request_id, {'ignored': True})
                            continue
                        roi = args.get('roi')
                        detection = replace(detection, roi=roi).validate(camera.shape)
                        viewport_empty = roi is None
                        detection_revision += 1
                        detection_changed_ns = time.perf_counter_ns()
                        for wait in waits.values():
                            wait['streak'] = 0
                            wait['after_ns'] = detection_changed_ns
                            wait['skip_queued'] = camera.pending_count()
                        reply(request_id, {'roi': roi, 'revision': detection_revision})
                    elif command in ('start', 'capture'):
                        if running: raise RuntimeError('CCD acquisition already running')
                        if saves: raise RuntimeError('Wait for image saving before restarting acquisition')
                        count = None
                        if command == 'capture':
                            count = positive_int(args.get('frames', 1), 'Frame count')
                            if count > max_frames:
                                raise ValueError(f'Capture exceeds bounded buffer ({max_frames} frames)')
                            capture_deadline = time.monotonic() + positive_seconds(args.get('timeout_s', 60))
                        frames.clear()
                        camera.start()
                        running = True
                        run_id += 1
                        acquired = 0
                        last_device_id = None
                        capture_count = count
                        capture_id = request_id if command == 'capture' else None
                        capture_save = args.get('save_path')
                        if command == 'start': reply(request_id, {'running': True, 'run_id': run_id})
                    elif command == 'stop':
                        stop()
                        reply(request_id, {'running': False})
                    elif command == 'wait':
                        if not running: raise RuntimeError('Start CCD acquisition before waiting for ions')
                        target = positive_int(args.get('target', 1), 'Target')
                        consecutive = positive_int(args.get('consecutive_frames', 3), 'Consecutive frames')
                        timeout = positive_seconds(args.get('timeout_s', 60))
                        waits[request_id] = {'target': target, 'required': consecutive, 'streak': 0,
                                             'deadline': time.monotonic()+timeout,
                                             'skip_queued': camera.pending_count(),
                                             'after_ns': time.perf_counter_ns()}
                    elif command == 'save':
                        if saves: raise RuntimeError('An image save is already in progress')
                        selected = tuple(frames) if args.get('sequence', False) else tuple(frames)[-1:]
                        roi = detection.roi if args.get('roi_only', False) else None
                        saves[request_id] = writer.submit(save_frames, args['path'], selected, roi)
                    else:
                        raise ValueError('Unknown CCD command: ' + command)
                except Exception as exc:
                    reply(request_id, error=(type(exc).__name__, str(exc)))
            if not alive: break

            for request_id, future in list(saves.items()):
                if future.done():
                    try: reply(request_id, future.result())
                    except Exception as exc: reply(request_id, error=(type(exc).__name__, str(exc)))
                    del saves[request_id]
            for request_id, wait in list(waits.items()):
                if time.monotonic() >= wait['deadline']:
                    reply(request_id, error=('TimeoutError', 'Ion detection condition timed out'))
                    del waits[request_id]
            if running and capture_id and time.monotonic() >= capture_deadline:
                request_id, capture_id = capture_id, None
                stop('CCD capture timed out')
                reply(request_id, error=('TimeoutError', 'CCD capture timed out'))
            if not running:
                pipe.poll(.005)
                continue
            read_started_ns = time.perf_counter_ns()
            frame = camera.read()
            if frame is None:
                pipe.poll(.001)
                continue
            image, device_id = frame
            if image.shape != camera.shape or image.dtype != np.uint16:
                raise ValueError('Unexpected camera frame shape or dtype')
            acquired += 1
            frame_id += 1
            gap = last_device_id is not None and device_id != last_device_id + 1
            last_device_id = device_id
            result = (dict(count=0, matched=False, centers=[], target=detection.target)
                      if follow_viewport and viewport_empty else detect_ions(image, detection))
            result.update(frame_id=frame_id, device_frame_id=device_id, run_id=run_id,
                          received_ns=read_started_ns, analyzed_ns=time.perf_counter_ns(),
                          detection_revision=detection_revision, frame_gap=gap)
            frames.append(image)
            # Never wait for UI painting. Skip a preview write if the reader owns the slot.
            if lock.acquire(False):
                try:
                    pixels[:h*w] = image.ravel()
                    centers = result['centers'][:MAX_MARKERS]
                    if centers: markers[:len(centers)] = centers
                    header[:] = (frame_id, h, w, read_started_ns, result['count'], detection.target,
                                 int(image.min()), int(image.max()), run_id, acquired,
                                 result['analyzed_ns'], detection_revision)
                finally: lock.release()
            for request_id, wait in list(waits.items()):
                # Wait for at least one exposure interval after arming the condition;
                # pre-existing SDK queue frames must not satisfy a new workflow wait.
                fresh_after = max(wait['after_ns'], detection_changed_ns) + int(camera.exposure_ms*1e6)
                queued_before_wait = wait['skip_queued'] > 0
                if queued_before_wait: wait['skip_queued'] -= 1
                if read_started_ns < fresh_after or gap or queued_before_wait:
                    wait['streak'] = 0
                    continue
                wait['streak'] = wait['streak']+1 if result['count'] >= wait['target'] else 0
                if wait['streak'] >= wait['required']:
                    reply(request_id, {**result, 'matched': True, 'target': wait['target'],
                                       'consecutive_frames': wait['streak']})
                    del waits[request_id]
            if capture_id and acquired >= capture_count:
                request_id, capture_id = capture_id, None
                camera.stop()
                running = False
                fail_waits('Finite acquisition ended before condition was met')
                if capture_save:
                    saves[request_id] = writer.submit(save_frames, capture_save, tuple(frames))
                else:
                    reply(request_id, {'frames': acquired, 'run_id': run_id, 'last_detection': result})
                pipe.send(('state', {'running': False, 'frames': acquired}))
    except (EOFError, BrokenPipeError):
        pass
    except BaseException as exc:
        try: pipe.send(('fatal', type(exc).__name__ + ': ' + str(exc)))
        except (EOFError, BrokenPipeError, OSError): pass
    finally:
        if camera is not None:
            try: camera.close()
            except Exception: pass
        writer.shutdown(wait=True)
        pipe.close()
