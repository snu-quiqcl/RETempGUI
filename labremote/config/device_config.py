"""Read RF *UI presets and limits* from each device family's device_config.yml.

This module is client-side only: it never communicates with a device and it
never changes hardware settings. Values are merged (defaults -> instruments[name]).
A missing/broken configuration is an error, never an excuse to disable limits.
"""
from __future__ import annotations

from copy import deepcopy
import math
from contextvars import ContextVar
from contextlib import contextmanager
_CONFIG_SNAPSHOT = ContextVar("config_snapshot", default=None)
from pathlib import Path
from labremote.config.paths import CONFIG_ROOT, registry_paths, read_yaml_document
from labremote.config.local_hardware import apply_local_connection


def _merge(left: dict, right: dict) -> dict:
    result = deepcopy(left)
    for key, value in right.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


_DOCUMENTS = {}


def _with_operation_settings(family, document):
    path = CONFIG_ROOT / 'operations' / family / 'operation_config.yml'
    if not path.exists(): return document
    operation = read_yaml_document(path)
    if not isinstance(operation, dict) or operation.get('schema_version') != 1:
        raise ValueError(f'{path}: expected schema_version: 1')
    for section in ('defaults', 'instruments'):
        if not isinstance(operation.get(section, {}), dict):
            raise ValueError(f'{path}: invalid {section}')
    entries = [operation.get('defaults', {}), *operation.get('instruments', {}).values()]
    if any(not isinstance(e, dict) or set(e)-{'rf_operation','scan_defaults'} for e in entries):
        raise ValueError(f'{path}: only rf_operation and scan_defaults are permitted')
    return _merge(document, operation)



def preload_device_configs():
    for path in CONFIG_ROOT.glob('devices/*/device_config.yml'):
        load_device_config(path.parent.name, '')


def validate_ramp_settings(max_step_vpp, interval_s):
    """Configuration validity, separate from registry parameter requests."""
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in (max_step_vpp, interval_s)):
        raise ValueError('Ramp step/interval must be finite numbers')
    if max_step_vpp <= 0 or interval_s < 0:
        raise ValueError('Ramp max_step_vpp must be positive and interval_s nonnegative')


def _validate_ramp_configs(document):
    if not isinstance(document, dict):
        return  # Structural errors are reported by load_device_config.
    defaults = document.get('defaults', {})
    instruments = document.get('instruments', {})
    if not isinstance(defaults, dict) or not isinstance(instruments, dict):
        return
    for overrides in ({}, *instruments.values()):
        if not isinstance(overrides, dict):
            continue
        merged = _merge(defaults, overrides)
        config = merged.get('rf_operation')
        if config is not None:
            validate_ramp_settings(config['max_step_vpp'], config['interval_s'])


def load_device_config(family: str, instrument_name: str = "") -> dict:
    if not family.isidentifier():
        raise ValueError(f'Invalid device family: {family}')
    config_path = (CONFIG_ROOT / 'devices' / family / 'device_config.yml')
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError('PyYAML required for RF config: pip install PyYAML') from exc
    # A bad config must fail CLOSED (rather than silently bypassing power caps).
    documents = _CONFIG_SNAPSHOT.get()
    if documents is None: documents = _DOCUMENTS
    if family not in documents:
        with config_path.open('r', encoding='utf-8') as stream:
            document = _with_operation_settings(family, yaml.safe_load(stream))
        _validate_ramp_configs(document)
        documents[family] = document
    document = deepcopy(documents[family])
    if not isinstance(document, dict) or document.get('schema_version') != 1:
        raise ValueError(f'{config_path}: expected schema_version: 1')
    defaults = document.get('defaults', {})
    instruments = document.get('instruments', {})
    if not isinstance(defaults, dict) or not isinstance(instruments, dict):
        raise ValueError(f'{config_path}: defaults and instruments must be dictionaries')
    overrides = instruments.get(instrument_name, {})
    if not isinstance(overrides, dict):
        raise ValueError(f'{config_path}: instruments.{instrument_name} must be a dictionary')
    return apply_local_connection(family, _merge(defaults, overrides))


def configured_instrument_names(family: str):
    """Names explicitly configured for this device family."""
    load_device_config(family)
    documents = _CONFIG_SNAPSHOT.get()
    if documents is None: documents = _DOCUMENTS
    return tuple(documents[family].get('instruments', {}))


def optional_number(config: dict, *path: str) -> float | None:
    current = config
    for segment in path:
        if not isinstance(current, dict):
            raise ValueError(f'Invalid config nesting: {".".join(path)}')
        if segment not in current:
            return None
        current = current[segment]
    if current is None:
        return None
    if isinstance(current, bool) or not isinstance(current, (float, int)):
        raise ValueError(f'Config {".".join(path)} must be a number or null')
    result = float(current)
    if not math.isfinite(result):
        raise ValueError(f'Config {".".join(path)} must be finite')
    return result


def dbm_to_vpp(dbm: float, impedance_ohm: float = 50.0) -> float:
    """Sine wave, 50-ohm terminated, *voltage across the load*."""
    return 2.0 * math.sqrt(2.0 * impedance_ohm * 0.001 * 10.0 ** (dbm / 10.0))


def vpp_to_dbm(vpp: float, impedance_ohm: float = 50.0) -> float:
    if not math.isfinite(vpp) or vpp <= 0:
        raise ValueError('Vpp must be finite and > 0')
    return 10.0 * math.log10(((vpp / (2 * math.sqrt(2))) ** 2 /
                              impedance_ohm) / 0.001)


def power_within_cap(dbm: float, cap_dbm: float | None) -> bool:
    return cap_dbm is None or dbm <= cap_dbm + 1e-9


# Existing RF callers share the same device configuration cache.
load_rf_device_config = load_device_config

@contextmanager
def operation_config():
    documents = {}
    import yaml
    for path in CONFIG_ROOT.glob('devices/*/device_config.yml'):
        document = _with_operation_settings(path.parent.name, read_yaml_document(path))
        _validate_ramp_configs(document)
        documents[path.parent.name] = document
    from labremote.runtime.parameters import REGISTRY_SNAPSHOT, ParameterRegistry
    policy = ParameterRegistry(registry_paths())
    token = _CONFIG_SNAPSHOT.set(documents)
    registry_token = REGISTRY_SNAPSHOT.set(policy)
    try: yield
    finally:
        REGISTRY_SNAPSHOT.reset(registry_token)
        _CONFIG_SNAPSHOT.reset(token)


def sg_power_cap_dbm(config, port):
    caps = []
    dbm = optional_number(config, 'outputs', port, 'limits', 'max_power_dbm')
    vpp = optional_number(config, 'outputs', port, 'limits', 'max_power_vpp')
    if dbm is not None: caps.append(dbm)
    if vpp is not None: caps.append(vpp_to_dbm(vpp))
    return min(caps) if caps else None
