"""One oven document: chamber, instrument names, profiles and power timing."""
from copy import deepcopy
import math
from labremote.configuration.paths import CONFIG_ROOT
from labremote.runtime.json_storage import read_json, save_json

LOCAL = CONFIG_ROOT / 'operations/oven.json'

def validate_chamber(chamber):
    if chamber not in ('EA', 'EC'):
        raise ValueError('Oven chamber must be EA or EC in operations/oven.json')
    return chamber

def validate_settings(data):
    if not isinstance(data, dict): raise ValueError('oven.json must be an object')
    result = deepcopy(data)
    validate_chamber(result['chamber'])
    for key in ('psu_name', 'relay_name'):
        if not isinstance(result[key], str) or not result[key].strip():
            raise ValueError(f'oven.json: {key} must be a server instrument name')
    if result['psu_name'] == result['relay_name']: raise ValueError('Use distinct PSU and relay names')
    if result['photoionization_shutter'] not in ('shutter_1', 'shutter_2'):
        raise ValueError('Select shutter_1 or shutter_2 in oven.json')
    result['shutter'] = result['photoionization_shutter']
    if type(result['timeout_s']) is not int or not 1 <= result['timeout_s'] <= 599999:
        raise ValueError('Oven timeout must be 1..599999 seconds')
    profiles = result['profiles']
    if not isinstance(profiles, dict): raise ValueError('oven.json: profiles must be an object')
    for name in ('EA_171', 'EA_174', 'EC_171', 'EC_174'):
        values = profiles.get(name)
        if not isinstance(values, (tuple, list)) or len(values) != 2 or any(type(v) not in (int,float) or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError(f'oven.json: {name} must contain positive [voltage V, current A]')
    for key in ('off_current_timeout_s','ramp_step_a','ramp_interval_s','off_current_tolerance_a','off_poll_s'):
        value = result['power'][key]
        if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'oven.json: power.{key} must be positive and finite')
    return result

def load_settings():
    return validate_settings(read_json(LOCAL))

def save_settings(data):
    # UI saves a subset: retain profiles, power policy and future fields.
    current = read_json(LOCAL)
    current.update(deepcopy(data))
    save_json(LOCAL, validate_settings(current))

DEFAULTS = load_settings()
PROFILES = deepcopy(DEFAULTS['profiles'])
