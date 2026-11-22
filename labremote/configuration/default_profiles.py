"""PC-owned operation defaults. Missing profiles never silently choose voltages."""
import json
from copy import deepcopy
from .paths import CONFIG_ROOT

def read_default(name):
    path=CONFIG_ROOT/'operations'/'defaults'/(name+'.json')
    try:
        value=json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError as exc:
        raise ValueError(f'Missing local default profile: {path}. Restore this PC configuration backup.') from exc
    if not isinstance(value,dict):raise ValueError(f'Expected a settings object: {path}')
    return deepcopy(value)
