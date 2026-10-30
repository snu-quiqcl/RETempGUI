"""Scope settings monitoring; waveform transfers are explicit acquisitions."""
from labremote.runtime.monitor import ParameterMonitor

PATHS = ('time_scale', 'time_offset', 'trigger_mode', 'trigger_status', 'trigger_source', 'trigger_level', 'trigger_slope', 'trigger_sweep', 'ch1_display', 'ch1_scale', 'ch1_offset', 'ch1_frequency', 'ch1_vpp', 'ch2_display', 'ch2_scale', 'ch2_offset', 'ch2_frequency', 'ch2_vpp')


class DS1052EMonitor(ParameterMonitor):
    def __init__(self, worker):
        super().__init__(worker, PATHS)
