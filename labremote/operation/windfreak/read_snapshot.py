from labremote.runtime.io import acquire
from labremote.runtime.bindings import bind_tree


def read_snapshot(p):
    p = bind_tree(p, 'windfreak')
    mode = acquire(p.reference_mode)
    hz = acquire(p.reference_frequency_hz)
    reference = dict(reference_mode=mode, reference_frequency_hz=hz,
                     configuration_matches_external=(mode == 'external' and 10e6 <= hz <= 100e6),
                     pll_lock={a: acquire(getattr(p, 'channel_' + a).pll_lock) for a in 'AB'},
                     external_reference_physically_verified=False)
    channels = {}
    for a in 'AB':
        ch = getattr(p, 'channel_' + a)
        state = {flag: acquire(getattr(ch, flag)) for flag in ('rf_enabled', 'pa_enabled', 'pll_enabled')}
        channels[a] = dict(channel=a, frequency_hz=acquire(ch.frequency_hz),
                           power_dbm=acquire(ch.power_dbm), phase_deg=acquire(ch.phase_deg),
                           phase_is_absolute=False,
                           phase_note='Last commanded relative phase step; no absolute readback',
                           pll_lock=reference['pll_lock'][a], output_enabled=all(state.values()), **state)
    return dict(device_info=acquire(p.device_info_json), reference=reference, channels=channels)
