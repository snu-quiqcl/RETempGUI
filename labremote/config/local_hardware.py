"""Private network endpoints; this module never connects to hardware."""
import json
from pathlib import Path

LOCAL_HARDWARE = Path(__file__).with_name('local_hardware.json')


def load_local_hardware():
    if not LOCAL_HARDWARE.exists():
        return {}
    try:
        data = json.loads(LOCAL_HARDWARE.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise ValueError('Cannot read local_hardware.json; check the local JSON file') from exc
    allowed = {'server_host', 'server_port', 'motor_host', 'motor_port'}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError('local_hardware.json: unsupported fields')
    for key, value in data.items():
        if key.endswith('_host'):
            if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value):
                raise ValueError(f'local_hardware.json: invalid {key}')
        elif type(value) is not int or not 1 <= value <= 65535:
            raise ValueError(f'local_hardware.json: invalid {key}')
    return data


def apply_local_connection(family, config):
    if family == 'motors':
        local = load_local_hardware()
        connection = config.setdefault('connection', {})
        for field in ('host', 'port'):
            if 'motor_' + field in local:
                connection[field] = local['motor_' + field]
    return config
