"""Windfreak monitoring: observation registration, unknown state and stale-read scheduling."""

FLAGS = ('rf_enabled', 'pa_enabled', 'pll_enabled')
CHANNEL_FIELDS = ('frequency_hz', 'power_dbm', 'phase_deg', 'pll_lock', *FLAGS)
SNAPSHOT_PATHS = ('reference_mode', 'reference_frequency_hz',
                  *(f'channel_{ch}.{field}' for ch in 'AB' for field in CHANNEL_FIELDS))


def empty_snapshot():
    return dict(device_info={},
                reference={'reference_mode':None, 'reference_frequency_hz':None,
                           'pll_lock':dict.fromkeys('AB'), 'configuration_matches_external':False},
                channels={ch:dict.fromkeys((*CHANNEL_FIELDS, 'output_enabled')) for ch in 'AB'},
                _parameter_states={path:{'quality':'unknown', 'verification':'none', 'error':None}
                                   for path in SNAPSHOT_PATHS})



from labremote.runtime.monitor import ParameterMonitor

class WindfreakMonitor(ParameterMonitor):
    def __init__(self, worker):
        super().__init__(worker, SNAPSHOT_PATHS)
