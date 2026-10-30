"""anapico observation paths; common scheduling never reads device state itself."""
from labremote.runtime.monitor import ParameterMonitor

PATHS = ('frequency', 'phase', 'output', 'reference_source', 'external_lock_frequency', 'locked', 'reference_output_enabled', 'reference_output_frequency')


class AnaPicoMonitor(ParameterMonitor):
    def __init__(self, worker):
        super().__init__(worker, PATHS)
