"""sg384 observation paths; common scheduling never reads device state itself."""
from labremote.runtime.monitor import ParameterMonitor

PATHS = ('frequency', 'phase', 'timebase_code', 'bnc_power_dbm', 'bnc_power_vpp', 'bnc_output', 'n_power_dbm', 'n_power_vpp', 'n_output')


class SG384Monitor(ParameterMonitor):
    def __init__(self, worker):
        super().__init__(worker, PATHS)
