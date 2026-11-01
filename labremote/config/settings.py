"""Settings for all GUI tabs, persisted under labremote/config."""
from __future__ import annotations
import json
from copy import deepcopy
import os
import sys
from pathlib import Path
BASE = Path(__file__).resolve().parents[2]
from labremote.config.paths import CONFIG_ROOT
from labremote.config.local_hardware import load_local_hardware
SETTINGS = CONFIG_ROOT / 'client_settings.json'
DEFAULTS = {'server_host': '127.0.0.1', 'server_port': 5555,
            'equipment_configuration': '', 'ccd_options': {}, 'operation_detailed_logging': False, 'windfreak_channel_names': {},
            'windfreak_names': [], 'sg384_names': [], 'anapico_names': [], 'dds4_names': [], 'ds1052e_names': [], 'mso7054_names':[], 'thermotek_names':[], 'keithley_names':[], 'osa_names':[], 'mdt_names':[], 'fpga_names':[], 'motors_names':[]}

def load_settings():
    data = deepcopy(DEFAULTS)
    if SETTINGS.exists():
        try:
            obj = json.loads(SETTINGS.read_text(encoding="utf-8"))
            data.update({k: v for k, v in obj.items() if k in DEFAULTS})
        except (OSError, ValueError) as exc:
            print(f"Warning: GUI settings not loaded: {exc}", file=sys.stderr)
    local = load_local_hardware()
    data.update({key: local[key] for key in ('server_host', 'server_port') if key in local})
    return data

def save_settings(data):
    temp = SETTINGS.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, SETTINGS)
