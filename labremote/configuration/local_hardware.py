"""Private network endpoints; this module never connects to hardware."""
import json
import os
from pathlib import Path

from .paths import CONFIG_ROOT
LOCAL_HARDWARE = CONFIG_ROOT / 'devices/connections.local.json'


def load_local_hardware():
    path = LOCAL_HARDWARE if LOCAL_HARDWARE.exists() else CONFIG_ROOT/'devices/connections.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError('Cannot read devices/connections.local.json; check the local JSON file') from exc
    allowed = {'server_host', 'server_port', 'motor_host', 'motor_port'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError('devices/connections.local.json: unsupported fields')
    for key, value in data.items():
        if key.endswith('_host'):
            if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value):
                raise ValueError(f'devices/connections.local.json: invalid {key}')
        elif type(value) is not int or not 1 <= value <= 65535:
            raise ValueError(f'devices/connections.local.json: invalid {key}')
    return data


def apply_local_connection(family, config):
    if family == 'motors':
        local = load_local_hardware()
        connection = config.setdefault('connection', {})
        for field in ('host', 'port'):
            if 'motor_' + field in local:
                connection[field] = local['motor_' + field]
    return config


def server_endpoint():
    """The connection document is the sole persisted InstrumentServer endpoint."""
    local=load_local_hardware()
    if not {'server_host','server_port'} <= local.keys():
        raise ValueError(
            f'Set server_host and server_port in {LOCAL_HARDWARE}. '
            'Use the IP of the PC running InstrumentServer; there is no automatic localhost fallback.')
    return local['server_host'],local['server_port']


def save_server_endpoint(host,port,*,expected=None):
    """Persist a user edit, retaining motor settings and detecting another writer."""
    host,port=validate_server_endpoint(host,port)
    local=load_local_hardware()
    if expected is not None and (local.get('server_host'),local.get('server_port'))!=tuple(expected):
        raise ValueError('Server configuration changed outside this window. Reload the application before saving.')
    local.update(server_host=host,server_port=port)
    payload=(json.dumps(local,ensure_ascii=False,indent=2)+'\n').encode('utf8')
    if LOCAL_HARDWARE.exists() and LOCAL_HARDWARE.read_bytes()==payload:return
    LOCAL_HARDWARE.parent.mkdir(parents=True,exist_ok=True)
    temporary=LOCAL_HARDWARE.with_name(LOCAL_HARDWARE.name+'.tmp')
    temporary.write_bytes(payload);os.replace(temporary,LOCAL_HARDWARE)


def validate_server_endpoint(host,port):
    if not isinstance(host,str):raise ValueError('Server Host must be a non-empty hostname or IP address')
    host=host.strip()
    if not host or any(c.isspace() for c in host):raise ValueError('Server Host must be a non-empty hostname or IP address')
    if type(port) is not int or not 1<=port<=65535:raise ValueError('Server Port must be 1..65535')
    return host,port
