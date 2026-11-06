"""Editable form defaults, separate from last-session values and hardware policies."""
import json
import math
from datetime import date
from .paths import CONFIG_ROOT

DEFAULT_INPUTS = CONFIG_ROOT / 'ui/input_defaults.json'


def validate_entry(entry):
    if not isinstance(entry, dict):
        raise ValueError('expected an object with kind and value')
    kind, value = entry.get('kind'), entry.get('value')
    valid = ((kind in ('text', 'multiline', 'choice') and isinstance(value, str)) or
             (kind == 'check' and type(value) is bool) or
             (kind == 'number' and type(value) in (int, float) and math.isfinite(value)))
    if not valid:
        raise ValueError('invalid kind/value; use text, multiline, choice, check or number')
    return entry


def load_input_defaults(path, report):
    """Invalid defaults never prevent recovery of the previous session."""
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data, dict) or data.get('schema_version') != 1:
            raise ValueError('expected schema_version: 1')
        inputs, families = data.get('inputs', {}), data.get('families', {})
        if not isinstance(inputs, dict) or not isinstance(families, dict):
            raise ValueError('inputs and families must be objects')
        clean = {'inputs': {}, 'families': {}}
        groups = [(inputs, clean['inputs'], 'inputs')]
        for family, entries in families.items():
            if not isinstance(entries, dict):
                report(f'{path}: families/{family} must be an object')
                continue
            clean['families'][family] = {}
            groups.append((entries, clean['families'][family], 'families/'+family))
        for source, destination, prefix in groups:
            for key, entry in source.items():
                try:destination[key] = validate_entry(entry)
                except ValueError as exc:report(f'{path}: {prefix}/{key}: {exc}')
        return clean
    except (OSError, ValueError) as exc:
        report(f'Defaults skipped: {path}: {exc}')
        return {'inputs': {}, 'families': {}}


def resolve_default(defaults, key):
    entry=None
    if key in defaults['inputs']:
        entry=defaults['inputs'][key]
    else:
        parts = key.split('/', 3)
        if len(parts) == 4 and parts[0] == 'device':
            entry=defaults['families'].get(parts[1], {}).get(parts[3])
    if entry is not None and entry['kind']=='text':
        parts=key.split('/',3)
        instrument=parts[2] if len(parts)==4 and parts[0]=='device' else ''
        entry=dict(entry,value=entry['value'].replace('${PROJECT_ROOT}',CONFIG_ROOT.parents[1].as_posix())
                   .replace('${TODAY}',date.today().isoformat()).replace('${INSTRUMENT}',instrument))
    return entry
