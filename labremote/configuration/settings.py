"""Settings for all GUI tabs, persisted under labremote/config."""
from __future__ import annotations
import json
from copy import deepcopy
import os
import sys
from pathlib import Path
BASE = Path(__file__).resolve().parents[2]
from labremote.configuration.paths import CONFIG_ROOT
from labremote.configuration.local_hardware import server_endpoint
SETTINGS = CONFIG_ROOT / 'ui/client_settings.local.json'
DEFAULTS = json.loads((CONFIG_ROOT / 'ui/defaults.json').read_text(encoding='utf-8'))
DEFAULTS['server_host'],DEFAULTS['server_port']=server_endpoint()

def load_settings():
    data = deepcopy(DEFAULTS)
    if SETTINGS.exists():
        try:
            obj = json.loads(SETTINGS.read_text(encoding="utf-8"))
            data.update({k: v for k, v in obj.items() if k in DEFAULTS and k not in ('server_host','server_port')})
        except (OSError, ValueError) as exc:
            print(f"Warning: GUI settings not loaded: {exc}", file=sys.stderr)
    data['server_host'],data['server_port']=server_endpoint()
    return data

def save_settings(data):
    # Endpoints are saved by save_server_endpoint, never by general UI settings.
    data={key:value for key,value in data.items() if key not in ('server_host','server_port')}
    SETTINGS.parent.mkdir(parents=True,exist_ok=True)
    temp = SETTINGS.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, SETTINGS)
