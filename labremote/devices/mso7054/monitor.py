from labremote.runtime.monitor import ParameterMonitor

PATHS = ('time_scale', 'time_offset', 'trigger_type', 'trigger_status', 'trigger_source', 'trigger_level', 'trigger_slope', 'sweep', 'ch1_display', 'ch1_scale', 'ch1_offset', 'ch1_vavg', 'ch1_vrms', 'ch1_vpp', 'ch1_vmax', 'ch1_vmin', 'ch2_display', 'ch2_scale', 'ch2_offset', 'ch2_vavg', 'ch2_vrms', 'ch2_vpp', 'ch2_vmax', 'ch2_vmin', 'ch3_display', 'ch3_scale', 'ch3_offset', 'ch3_vavg', 'ch3_vrms', 'ch3_vpp', 'ch3_vmax', 'ch3_vmin', 'ch4_display', 'ch4_scale', 'ch4_offset', 'ch4_vavg', 'ch4_vrms', 'ch4_vpp', 'ch4_vmax', 'ch4_vmin')

class MSO7054Monitor(ParameterMonitor):
    def __init__(self,worker):super().__init__(worker,PATHS)
