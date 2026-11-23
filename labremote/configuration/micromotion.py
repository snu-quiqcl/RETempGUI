"""Local Two-RF settings; no instrument I/O or fallback voltages."""
import json
import math
from .paths import CONFIG_ROOT

def two_rf_settings_path(chamber):
    if chamber not in ('EA', 'EC'):
        raise ValueError('Invalid chamber')
    from labremote.devices.fpga.mapping import settings_path
    return settings_path(CONFIG_ROOT / 'operations' / 'micromotion' / (chamber + '.two_rf.json'))

def two_rf_settings(chamber):
    path = two_rf_settings_path(chamber)
    try:
        from .experiment_settings import read
        value = read(path)
    except FileNotFoundError as exc:
        original=CONFIG_ROOT/'operations'/'micromotion'/(chamber+'.two_rf.json')
        if path!=original and original.exists():
            value=json.loads(original.read_text(encoding='utf-8-sig'))
        else:
            raise ValueError(f'Restore local Two-RF settings: {path}') from exc
    if not isinstance(value,dict):raise ValueError(f'Invalid Two-RF settings: {path}')
    for name in ('rf_low', 'rf_high'):
        number = value.get(name)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number <= 0:
            raise ValueError(f'{path}: {name} must be a positive finite Vpp value')
    if value['rf_low'] >= value['rf_high']:
        raise ValueError(f'{path}: rf_low must be below rf_high')
    return value
