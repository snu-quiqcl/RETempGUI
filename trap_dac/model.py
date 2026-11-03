"""Voltage sets keyed by stable electrode IDs, separate from physical wiring."""
from __future__ import annotations
import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from decimal import Decimal
from datetime import datetime
from pathlib import Path
from .configuration import DeviceConfig, number, read_json, voltage_code


def default_set_name(device, now=None):
    return f"{device}_{(now or datetime.now()):%Y%m%d_%H%M%S}"


def suggested_filename(device, name='', now=None):
    stamp = (now or datetime.now()).strftime('%Y%m%d_%H%M%S')
    name = name.strip()
    if re.fullmatch(r'(?:EA|EC)_\d{8}_\d{6}', name) or name == 'Untitled':
        name = ''
    if name.startswith(device + '_'):
        name = name[len(device) + 1:]
    safe = ''.join(c if c.isalnum() or c in '_- ' else '_' for c in name).strip()
    return f'{stamp}_{device}' + (f'_{safe}' if safe else '') + '.json'


@dataclass(frozen=True)
class Command:
    electrode_id: str
    chip: int
    channel: int
    voltage: float
    code: int


@dataclass(frozen=True)
class VoltageSet:
    config: DeviceConfig
    voltages: tuple[float, ...]
    name: str = 'Untitled'
    notes: str = ''

    @property
    def device(self):
        return self.config.device

    @property
    def by_id(self):
        return {e.id: value for e, value in zip(self.config.electrodes, self.voltages)}

    def validate(self):
        if not isinstance(self.name, str) or not isinstance(self.notes, str):
            raise ValueError('Preset name and notes must be text.')
        if not isinstance(self.voltages, (tuple, list)) or len(self.voltages) != len(self.config.electrodes):
            raise ValueError('A voltage is required for every configured electrode.')
        for electrode, value in zip(self.config.electrodes, self.voltages):
            voltage_code(self.config, electrode.chip, electrode.channel, value)
        return self

    def commands(self):
        self.validate()
        pairs = sorted(zip(self.config.electrodes, self.voltages), key=lambda item: (item[0].chip, item[0].channel))
        return tuple(Command(e.id, e.chip, e.channel, float(value),
                             voltage_code(self.config, e.chip, e.channel, value)) for e, value in pairs)

    def signature(self):
        return self.device, self.config.wiring(), tuple(sorted(self.by_id.items()))

    def as_dict(self, **metadata):
        self.validate()
        data = {'format': 'trap-dac-ui', 'schema_version': 3, 'device': self.device,
                'name': self.name, 'notes': self.notes, 'voltages': self.by_id,
                'saved_at': datetime.now().astimezone().isoformat(),
                'configuration': self.config.as_dict()}
        data.update(metadata)
        return data

    @classmethod
    def from_values(cls, config, values, **kwargs):
        if not isinstance(values, dict) or set(values) != set(config.by_id):
            raise ValueError('Preset electrode IDs do not match the current configuration.')
        return cls(config, tuple(values[e.id] for e in config.electrodes), **kwargs).validate()

    @classmethod
    def from_dict(cls, data, config):
        if not isinstance(data, dict) or data.get('format') != 'trap-dac-ui':
            raise ValueError('Unsupported preset format.')
        version = data.get('schema_version')
        if type(version) is not int or version not in (1, 2, 3):
            raise ValueError('Unsupported preset schema version.')
        if data.get('device') != config.device:
            raise ValueError(f'Open a {config.device} preset in this tab.')
        if version == 1:
            values = legacy_values(data, config)
        else:
            saved_config = DeviceConfig.from_dict(data.get('configuration'), config.device)
            if saved_config.wiring() != config.wiring():
                raise ValueError('Preset wiring differs from the current configuration. Restore the matching configuration before loading this set.')
            values = data.get('voltages')
        # Old shift metadata never overrides the explicitly saved voltages.
        return cls.from_values(config, values,
                               name=data.get('name', default_set_name(config.device)), notes=data.get('notes', ''))


def legacy_values(data, config):
    """Version-1 arrays used fixed hardware channels, never a screen order."""
    n = 9 if config.device == 'EA' else 8
    values, wiring = {}, []
    for chip, key, prefix in ((0, 'left', 'L'), (1, 'right', 'R')):
        side = data.get(key)
        if not isinstance(side, list) or len(side) != n:
            raise ValueError(f'Legacy {config.device} presets require {n} values per side.')
        for channel, value in enumerate(side):
            eid = prefix + '_IN' if channel == n-1 else f'{prefix}{channel}'
            values[eid] = value
            wiring.append((eid, chip, channel))
    if tuple(sorted(wiring)) != config.wiring():
        raise ValueError('Legacy preset uses the original fixed wiring. The current configuration has different electrode IDs or DAC assignments.')
    return values


def inner_components(left, right):
    """Half-sum and half-difference: a component step changes each side by that step."""
    left, right = number(left, 'innerDC left'), number(right, 'innerDC right')
    return left / 2 + right / 2, left / 2 - right / 2


def inner_voltages(config, sym, asym):
    """Validate both outputs before the caller updates either draft voltage."""
    if config.inner_pair is None:
        raise ValueError('Sym / Asym requires exactly one innerDC electrode on each side.')
    sym, asym = number(sym, 'Sym'), number(asym, 'Asym')
    values = {}
    for electrode, voltage in zip(config.inner_pair, (sym + asym, sym - asym)):
        voltage_code(config, electrode.chip, electrode.channel, voltage)
        values[electrode.id] = voltage
    return values


def outer_dc_factors(config, component):
    """Resolve EC electrode numbers through the current JSON wiring, never array order."""
    if config.device != 'EC' or component not in ('x', 'y', 'squeeze', 'squeeze4'):
        raise ValueError('Outer DC X / Y / Squeeze is available only for EC.')
    left = {'13', '14', '15', '16', '17', '18'}
    right = {'48', '47', '46', '45', '44', '43'}
    selected = {}
    for label in sorted(left | right, key=int):
        matches = [e for e in config.electrodes if e.label.strip() == label]
        if len(matches) != 1 or matches[0].role != 'outer':
            raise ValueError(f'Outer DC Quick needs one outer electrode labeled {label} in EC.json.')
        electrode = matches[0]
        expected_side = 'left' if label in left else 'right'
        if electrode.side != expected_side:
            raise ValueError(f'Outer DC electrode {label} must be on the {expected_side} in EC.json.')
        selected[label] = electrode
    positive = {
        'x': left,
        'y': {'13', '14', '15', '48', '47', '46'},
        'squeeze': {'15', '16', '46', '45'},
        'squeeze4': {'14', '15', '16', '17', '47', '46', '45', '44'},
    }[component]
    # 12, 49, innerDC and any other configured electrodes receive no step.
    return {e.id: 1 if label in positive else -1 for label, e in selected.items()}


def step_set(state, step, direction, *, electrode_id=None, component=None):
    """Build a fully validated Quick target without mutating the current set."""
    state.validate()
    step = number(step, 'Step')
    if step <= 0:
        raise ValueError('Step must be positive.')
    if type(direction) is not int or direction not in (-1, 1):
        raise ValueError('Step direction must be +1 or -1.')
    if (electrode_id is None) == (component is None):
        raise ValueError('Choose one electrode or one DC component.')
    if electrode_id is not None:
        if electrode_id not in state.config.by_id:
            raise ValueError('Electrode is not in the current configuration.')
        factors = {electrode_id: 1}
    elif component in ('x', 'y', 'squeeze', 'squeeze4'):
        factors = outer_dc_factors(state.config, component)
    else:
        pair = state.config.inner_pair
        if component not in ('sym', 'asym') or pair is None:
            raise ValueError('Sym / Asym requires exactly one innerDC on each side.')
        factors = {pair[0].id: 1, pair[1].id: 1 if component == 'sym' else -1}
    values = state.by_id
    # Decimal steps avoid accumulating binary rounding errors on repeated clicks.
    delta = Decimal(str(step)) * direction
    for eid, factor in factors.items():
        values[eid] = float(Decimal(str(values[eid])) + delta * factor)
    return replace(state, voltages=tuple(values[e.id] for e in state.config.electrodes)).validate()


def example(config):
    return VoltageSet(config, tuple(e.default_voltage for e in config.electrodes),
                      name=default_set_name(config.device),
                      notes='Initial voltages from the device configuration.').validate()


def atomic_json(path, data):
    atomic_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def atomic_text(path, text, encoding='utf-8'):
    """Replace a text file only after its complete contents have been written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.dac_', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding=encoding, newline='') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_preset(path, config):
    return VoltageSet.from_dict(read_json(path), config)
