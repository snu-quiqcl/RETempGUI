"""GUI configuration, stored in one PC-owned JSON document."""
from copy import deepcopy
from .paths import CONFIG_ROOT
from .local_hardware import server_endpoint
from labremote.runtime.json_storage import read_json, save_json

SETTINGS = CONFIG_ROOT / 'ui/client_settings.json'
DEFAULTS = read_json(SETTINGS)
DEFAULTS['server_host'], DEFAULTS['server_port'] = server_endpoint()

def load_settings():
    data = read_json(SETTINGS)
    if not isinstance(data, dict): raise ValueError(f'Expected a settings object: {SETTINGS}')
    data['server_host'], data['server_port'] = server_endpoint()
    return data

def save_settings(data):
    current = read_json(SETTINGS) if SETTINGS.exists() else {}
    current.update(deepcopy(data))
    current.pop('server_host', None); current.pop('server_port', None)
    save_json(SETTINGS, current)
