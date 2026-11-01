import json
import os
from pathlib import Path

from labremote.config.paths import CONFIG_ROOT
LOCAL = CONFIG_ROOT/'operations/oven.local.json'
PROFILES = {'EA_174': (5., .75), 'EA_171': (5., .75),
            'EC_174': (5., 1.4), 'EC_171': (5., 1.30)}
DEFAULTS = {'chamber': 'EC', 'psu_name': 'oven_psu', 'relay_name': 'oven_relays',
            'shutter': 'shutter_2', 'photoionization_shutter': 'shutter_1', 'timeout_s':600}


def load_settings():
    if not LOCAL.exists(): return dict(DEFAULTS)
    data = json.loads(LOCAL.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict): raise ValueError('oven.local.json must be an object')
    result = dict(DEFAULTS)
    result.update({key: value for key, value in data.items() if key in DEFAULTS})
    validate_chamber(result['chamber'])
    if result['photoionization_shutter'] not in ('shutter_1','shutter_2'):
        raise ValueError('Select shutter_1 or shutter_2 for the 399 shutter')
    if result['shutter'] not in ('shutter_1', 'shutter_2'):
        raise ValueError('Select shutter_1 or shutter_2 in oven.local.json')
    if type(result['timeout_s']) is not int or not 1<=result['timeout_s']<=599999:raise ValueError('Oven timeout must be 1..599999 seconds')
    return result


def validate_chamber(chamber):
    if chamber not in ('EA','EC'):raise ValueError('Oven chamber must be EA or EC in operations/oven.local.json')
    return chamber


def save_settings(data):
    validate_chamber(data.get('chamber','EC'))
    if data.get('photoionization_shutter','shutter_1') not in ('shutter_1','shutter_2'):raise ValueError('Invalid 399 shutter')
    duration=data.get("timeout_s",600)
    if type(duration) is not int or not 1<=duration<=599999:raise ValueError("Timeout must be at least 0분 1초")
    temp = LOCAL.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    os.replace(temp, LOCAL)
