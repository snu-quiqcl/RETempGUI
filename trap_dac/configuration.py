"""Validated per-device DAC wiring and display positions loaded from JSON."""
from __future__ import annotations
import json
import math
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent.parent / 'configs'


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label}: a numeric value is required.')
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(f'{label}: the number is too large.') from exc
    if not math.isfinite(value):
        raise ValueError(f'{label}: NaN and infinity are not allowed.')
    return value


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label}: an integer from {low} to {high} is required.')
    return value


def read_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    with Path(path).open(encoding='utf-8-sig') as stream:
        return json.load(stream, object_pairs_hook=unique_pairs)


@dataclass(frozen=True)
class Electrode:
    id: str
    label: str
    chip: int
    channel: int
    side: str
    row: int
    role: str = 'outer'
    default_voltage: float = 0.0

    def as_dict(self):
        result = {'id': self.id, 'label': self.label, 'chip': self.chip,
                  'channel': self.channel, 'position': {'side': self.side, 'row': self.row},
                  'role': self.role, 'default_voltage': self.default_voltage}
        return result


@dataclass(frozen=True)
class DeviceConfig:
    device: str
    default_port: str
    electrodes: tuple[Electrode, ...]
    offsets: tuple[tuple[float, ...], ...]

    @property
    def by_id(self):
        return {e.id: e for e in self.electrodes}

    def for_side(self, side):
        return tuple(sorted((e for e in self.electrodes if e.side == side), key=lambda e: e.row))

    @property
    def inner_pair(self):
        """Select one innerDC per display side, independently of DAC wiring."""
        left = [e for e in self.electrodes if e.role == 'inner' and e.side == 'left']
        right = [e for e in self.electrodes if e.role == 'inner' and e.side == 'right']
        return (left[0], right[0]) if len(left) == len(right) == 1 else None

    def wiring(self):
        """Display positions and labels do not determine electrical identity."""
        return tuple(sorted((e.id, e.chip, e.channel) for e in self.electrodes))

    def as_dict(self):
        return {'schema_version': 1, 'device': self.device, 'default_port': self.default_port,
                'hardware': {'chips': 2, 'outputs_per_chip': 16, 'range_v': 20},
                'calibration_offsets': [list(side) for side in self.offsets],
                'electrodes': [e.as_dict() for e in self.electrodes]}

    @classmethod
    def from_dict(cls, data, expected_device=None):
        if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
            raise ValueError('Configuration schema_version must be 1.')
        device = data.get('device')
        if device not in ('EA', 'EC') or (expected_device and device != expected_device):
            raise ValueError(f"Expected configuration for {expected_device or 'EA or EC'}.")
        hw = data.get('hardware')
        if not isinstance(hw, dict):
            raise ValueError('hardware must describe two 16-output DAC chips.')
        integer(hw.get('chips'), 2, 2, 'hardware.chips')
        integer(hw.get('outputs_per_chip'), 16, 16, 'hardware.outputs_per_chip')
        if number(hw.get('range_v'), 'hardware.range_v') != 20:
            raise ValueError('This driver uses the +/-20 V range.')
        port = data.get('default_port', '')
        if not isinstance(port, str):
            raise ValueError('default_port must be text.')
        offsets = data.get('calibration_offsets')
        if not isinstance(offsets, list) or len(offsets) != 2:
            raise ValueError('calibration_offsets must contain two arrays of 16 values.')
        checked_offsets = []
        for chip, row in enumerate(offsets):
            if not isinstance(row, list) or len(row) != 16:
                raise ValueError(f'calibration_offsets[{chip}] requires 16 values.')
            checked_offsets.append(tuple(number(v, f'offset {chip}:{ch}') for ch, v in enumerate(row)))
        # Legacy v_shift / shift_factor metadata is ignored. Explicit electrode
        # voltages are authoritative, including in previously linked configs.
        items = data.get('electrodes')
        if not isinstance(items, list) or not 1 <= len(items) <= 32:
            raise ValueError('electrodes must list 1 to 32 used outputs.')
        electrodes, ids, outputs, positions = [], set(), set(), set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError('Each electrode must be an object.')
            eid = item.get('id')
            if not isinstance(eid, str) or not eid.strip() or eid in ids:
                raise ValueError('Every electrode needs a unique nonempty id.')
            label = item.get('label', eid)
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f'{eid}: label must be nonempty text.')
            chip = integer(item.get('chip'), 0, 1, f'{eid}.chip')
            channel = integer(item.get('channel'), 0, 15, f'{eid}.channel')
            if (chip, channel) in outputs:
                raise ValueError(f'Duplicate DAC output: chip {chip}, CH {channel}.')
            position = item.get('position')
            if not isinstance(position, dict) or position.get('side') not in ('left', 'right'):
                raise ValueError(f'{eid}: position.side must be left or right.')
            side = position['side']
            row = integer(position.get('row'), 0, 63, f'{eid}.position.row')
            if (side, row) in positions:
                raise ValueError(f'Duplicate screen position: {side}, row {row}.')
            role = item.get('role', 'outer')
            if role not in ('outer', 'inner'):
                raise ValueError(f'{eid}: role must be outer or inner.')
            voltage = number(item.get('default_voltage', 0), f'{eid}.default_voltage')
            electrodes.append(Electrode(eid, label, chip, channel, side, row, role, voltage))
            ids.add(eid)
            outputs.add((chip, channel))
            positions.add((side, row))
        config = cls(device, port, tuple(electrodes), tuple(checked_offsets))
        for e in config.electrodes:
            voltage_code(config, e.chip, e.channel, e.default_voltage)
        return config


def voltage_code(config, chip, channel, voltage):
    integer(chip, 0, 1, 'chip')
    integer(channel, 0, 15, 'channel')
    voltage = number(voltage, f'DAC {chip}:{channel}')
    if not -20 <= voltage <= 20:
        raise ValueError(f'DAC {chip}:{channel}: {voltage:g} V is outside +/-20 V.')
    offset = config.offsets[chip][channel]
    raw = (voltage - offset) / 40.0 * 65536 + 32768
    if not -20 <= voltage - offset <= 20 - 40.0 / 65536:
        raise ValueError(f'DAC {chip}:{channel}: {voltage:g} V exceeds the calibrated range (offset {offset:+g} V).')
    return int(raw)


def load_config(path, device=None):
    try:
        return DeviceConfig.from_dict(read_json(path), device)
    except (OSError, ValueError) as exc:
        raise ValueError(f'Configuration {path}: {exc}') from exc


def load_configs(folder=DEFAULT_CONFIG_DIR):
    return {device: load_config(Path(folder) / f'{device}.json', device) for device in ('EA', 'EC')}
