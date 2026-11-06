"""Validated settings; physical input pins resolve through the installed bitstream map."""
import math
import json
from pathlib import Path
import numpy as np
from labremote.devices.fpga.vendor import HardwareDefinition_remote_ent_test_ec as hd
from labremote.devices.dac.model import atomic_json as save

ROOT = Path(__file__).resolve().parents[1] / 'config/operations/micromotion'
PINS = dict(hd.input_mapping)
STOPWATCH_PINS = tuple(p for p, name in PINS.items() if hasattr(hd, name + '_stopwatch_result'))
COUNTER_PINS = tuple(p for p, name in PINS.items() if hasattr(hd, name + '_counter_result'))


def defaults(chamber='EC'):
    return dict(schema_version=1, chamber=chamber, trg_pin='ja_2',
                pmt_pin='jb_4' if chamber == 'EC' else 'jb_6', counter_pin='',
                rf_mhz=30.6314, events=10000, batches=1, periods=1,
                timeout_s=30., settle_s=.1, gate_us=100., rf_repeats=500,
                left=[.690, .710, .001], right=[.265, .285, .001], use_ldac=True)


def grid(spec):
    if not isinstance(spec, (list, tuple)) or len(spec) != 3:
        raise ValueError('Voltage range requires min, max, step')
    lo, hi, step = map(float, spec)
    if not all(math.isfinite(v) for v in (lo, hi, step)) or step <= 0 or hi <= lo:
        raise ValueError('Scan requires finite min < max and step > 0 on both axes')
    count = (hi-lo)/step
    if not math.isclose(count, round(count), abs_tol=1e-7) or not 2 <= round(count) <= 1000:
        raise ValueError('Each axis requires 3..1001 points and an integer number of steps')
    return np.linspace(lo, hi, round(count)+1)


def validate(settings):
    c = dict(settings)
    if c.get('schema_version') != 1 or c.get('chamber') not in ('EA', 'EC'):
        raise ValueError('Invalid micromotion schema/chamber')
    for key in ('trg_pin', 'pmt_pin'):
        if c.get(key) not in STOPWATCH_PINS:
            raise ValueError(f'{key}: select a stopwatch-capable input')
    if c['trg_pin'] == c['pmt_pin']:
        raise ValueError('TRG and PMT must use distinct physical inputs')
    if c.get('counter_pin') not in ('', *COUNTER_PINS):
        raise ValueError('RF test needs a counter-capable input; ja_2 has no counter')
    for key, low, high in [('rf_mhz', 1., 100.), ('timeout_s', 1., 3600.),
                          ('settle_s', 0., 60.), ('gate_us', .1, 500.)]:
        value = float(c[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{key} must be in {low}..{high}')
        c[key] = value
    for key, low, high in [('events', 10, 10000000), ('batches', 1, 1000),
                          ('periods', 1, 20), ('rf_repeats', 1, 1000)]:
        if type(c[key]) is not int or not low <= c[key] <= high:
            raise ValueError(f'{key} must be an integer in {low}..{high}')
    if type(c['use_ldac']) is not bool:
        raise ValueError('use_ldac must be boolean')
    xs, ys = grid(c['left']), grid(c['right'])
    if len(xs)*len(ys) > 10000:
        raise ValueError('Scan is limited to 10000 points')
    if max(abs(xs).max(), abs(ys).max()) > 20:
        raise ValueError('Scan voltages exceed +/-20 V')
    if bins(c) > 1023:
        raise ValueError('Observation window exceeds FPGA histogram memory')
    if c['rf_mhz']*c['gate_us'] > 50000:
        raise ValueError('RF test gate risks 16-bit counter overflow; shorten gate')
    return c


def bins(c):
    # Padding for FIFO triples is separate from the requested physical RF window.
    return int(math.ceil(1000*c['periods']/c['rf_mhz']/1.25/3))*3


def fit_indices(c):
    return np.arange(1, min(bins(c), int(math.ceil(1000*c['periods']/c['rf_mhz']/1.25))))


def load(path=None, chamber='EC'):
    path = Path(path or ROOT / (chamber+'.local.json'))
    return validate(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else defaults(chamber)
