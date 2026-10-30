from labremote.runtime.monitor import ParameterMonitor
PATHS = ('frequency_start_thz', 'frequency_stop_thz', 'reference_level_dbm', 'db_per_div', 'auto_reference', 'trace_name')

class Monitor(ParameterMonitor):
    def __init__(self, worker):super().__init__(worker, PATHS)
