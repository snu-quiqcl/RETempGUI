"""Only imported in the camera process; no SDK or hardware at UI startup."""
import time
import numpy as np


class DummyCamera:
    def __init__(self, options):
        self.shape = tuple(options.get('dummy_shape', (240, 320)))
        if len(self.shape) != 2 or any(type(v) is not int or v < 1 for v in self.shape):
            raise ValueError('Invalid dummy sensor shape')
        self.exposure_ms = 30.
        self.gain = 0
        self.sequence = 0
        self.running = False
        self.ions = int(options.get('dummy_ions', 3))

    def configure(self, exposure_ms=None, gain=None):
        if exposure_ms is not None: self.exposure_ms = exposure_ms
        if gain is not None: self.gain = gain

    def start(self):
        self.running = True
        self.next_frame = time.monotonic() + self.exposure_ms / 1000

    def read(self):
        now = time.monotonic()
        if not self.running or now < self.next_frame: return None
        self.next_frame = now + self.exposure_ms / 1000
        self.sequence += 1
        image = np.full(self.shape, 100, dtype=np.uint16)
        for index in range(self.ions):
            x, y = 30 + (index % 8) * 35, 30 + (index // 8) * 35
            image[y:y+7, x:x+7] = 4000
        return image, self.sequence

    def stop(self): self.running = False
    def close(self): self.stop()
    def pending_count(self): return 0


class ThorCamera:
    def __init__(self, options):
        from .vendor.QuIQCL_ThorCam import QuIQCL_ThorCam
        self.cam = QuIQCL_ThorCam(options.get('dll_path') or None)
        serials = list(self.cam.get_cam_list())
        serial = options.get('serial')
        if not serial:
            if len(serials) != 1:
                raise ValueError('Specify camera serial; found: ' + ', '.join(map(str, serials)))
            serial = serials[0]
        self.cam.cam_serial = serial
        try:
            self.cam.open_cam()
            if self.cam.is_color_supported():
                raise ValueError('This CCD integration requires a monochrome camera')
            self.cam.get_sensor_size()
            self.cam.get_roi()
            self.cam.get_exposure_range()
            self.cam.get_gain_range()
            self.exposure_ms = self.cam.get_exposure_ms()
            self.gain = self.cam.get_gain()
            self.cam.set_trigger_type('SW Trigger')
            self.cam.set_trigger_count(0)
            # Bounded SDK queue; dropped device frame numbers reset condition streaks.
            self.cam.set_frame_queue_size(8)
            self.shape = (int(self.cam.roi_height), int(self.cam.roi_width))
        except Exception:
            self.cam.close_cam()
            raise

    def configure(self, exposure_ms=None, gain=None):
        if exposure_ms is not None:
            self.cam.set_exposure_ms(exposure_ms)
            self.exposure_ms = self.cam.get_exposure_ms()
        if gain is not None:
            self.cam.set_gain(gain)
            self.gain = self.cam.get_gain()

    def start(self):
        # Discard previous run's buffered frames before issuing a new trigger.
        for _ in range(32):
            if self.cam.read_frame() is None: break
        self.cam.play_camera()

    def pending_count(self): return int(self.cam._cam.get_NumberOfQueuedFrames())

    def read(self):
        frame = self.cam.read_frame()
        if frame is None: return None
        data, fmt, (width, height), number, _, _ = frame
        if fmt != 'gray16le': raise ValueError('Expected a 16-bit monochrome frame')
        # Preserve unsigned values and conventional row-major sensor coordinates.
        return np.asarray(data, dtype=np.uint16).reshape(height, width), int(number)

    def stop(self): self.cam.stop_camera()
    def close(self):
        try: self.stop()
        finally: self.cam.close_cam()
