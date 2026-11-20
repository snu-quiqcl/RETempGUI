from labremote.runtime.device_worker import DeviceWorker
from labremote.runtime.io import acquire


class AFG2105Worker(DeviceWorker):
    family = 'afg2105'
    _scan_owner = None

    def reserve_scan(self, owner):
        with self._lock:
            if self._scan_owner is not None or self.has_foreground_requests():
                raise RuntimeError('AFG2105 is occupied')
            if self.ps is None or self.connection_error or self._closing:
                raise ConnectionError('Connect AFG2105 first')
            self._scan_owner=owner
            reads=[h for h in [self._active,*self._pending] if h is not None and not h.done.is_set()]
        try:
            for handle in reads:handle.wait()
        except BaseException:
            self.release_scan(owner);raise
        self.busy_changed.emit(True)

    def release_scan(self, owner):
        with self._lock:
            if self._scan_owner is owner:self._scan_owner=None
        self.busy_changed.emit(False)

    def cancel_power_ramp(self):
        if self._scan_owner is not None:self.cancel_backgrounds()
        else:super().cancel_power_ramp()

    def enqueue(self, handle):
        with self._lock:
            if self._scan_owner is not None and getattr(handle.group,'owner',None) is not self._scan_owner:
                if getattr(handle,'automatic_monitor',False):
                    self._monitor_pending.discard(handle.monitor_key);handle.finish()
                else:
                    error=RuntimeError('AFG2105 is reserved by Secular Frequency Scan; Stop the scan before disconnecting or changing settings')
                    handle.finish(error);self.failure.emit(handle.action,str(error))
                return handle
            return super().enqueue(handle)

    def make_monitor(self):
        from .monitor import AFG2105Monitor
        return AFG2105Monitor(self)

    def identify(self):
        identity = acquire(self.ps.IDN)
        if not isinstance(identity, dict) or str(identity.get('model','')).upper() != 'AFG-2105':
            raise ConnectionError('Expected AFG-2105: '+str(identity))
        return {'idn': identity, 'family': self.family}
