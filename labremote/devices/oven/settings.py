import json
import os
from pathlib import Path

LOCAL = Path(__file__).resolve().parents[2]/'config'/'oven.local.json'
PROFILES = {'EA_174': (5., .75), 'EA_171': (5., .75),
            'EC_174': (5., 1.4), 'EC_171': (5., 1.30)}
DEFAULTS = {'psu_name': 'oven_psu', 'relay_name': 'oven_relays',
            'shutter': 'shutter_2'}


def load_settings():
    if not LOCAL.exists(): return dict(DEFAULTS)
    data = json.loads(LOCAL.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict): raise ValueError('oven.local.json must be an object')
    result = dict(DEFAULTS)
    result.update({key: value for key, value in data.items() if key in DEFAULTS})
    if result['shutter'] not in ('shutter_1', 'shutter_2'):
        raise ValueError('Select shutter_1 or shutter_2 in oven.local.json')
    return result


def save_settings(data):
    temp = LOCAL.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    os.replace(temp, LOCAL)
