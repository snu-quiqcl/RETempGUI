"""Editable experiment parameters; hardware names come only from vendor definitions."""
import math
from copy import deepcopy
from pathlib import Path
from labremote.characterization.config import read, save
from labremote.config.paths import CONFIG_ROOT
from labremote.devices.fpga.controller import hd, OUTPUTS

ROOT = CONFIG_ROOT / 'operations/entanglement'
FIELDS = [
    ('batches', 'Batches', 1, 1000000, 0),
    ('groups_per_loop', 'Groups / FPGA loop', 1, 65535, 0),
    ('inner_trials', 'Inner trials / group', 1, 65535, 0),
    ('fpga_loops', 'FPGA loops / batch', 1, 65535, 0),
    ('cooling_us', 'Cooling (µs)', .05, 655.40, 2),
    ('initialization_us', 'Initialization (µs)', .05, 655.40, 2),
    ('aom_off_us', 'AOM OFF wait (µs)', .03, 655.35, 2),
    ('stopwatch_wait_us', 'Stopwatch wait (µs)', .04, 655.35, 2),
    ('decay_lower_a', 'PMTA lower bin', 0, 119, 0),
    ('decay_lower_c', 'PMTC lower bin', 0, 119, 0),
    ('coincidence_half_window_bins', 'Coincidence half-window (bins)', 1, 120, 0),
    ('mirror_wait_ms', 'Mirror settling (ms)', .5, 32767.5, 1),
    ('detection_us', 'State detection (µs)', .01, 655.35, 2),
    ('threshold_ea', 'EA bright threshold: counts >', 0, 65535, 0),
    ('threshold_ec', 'EC bright threshold: counts >', 0, 65535, 0),
    ('pi_ea_us', 'EA resonant π time (µs)', .14, 1310.84, 2),
    ('pi_ec_us', 'EC resonant π time (µs)', .14, 1310.84, 2),
    ('detuning_hz', 'Detuning (Hz) — timing only', -10000000, 10000000, 2),
    ('phase_magnitude_deg', 'Start-phase magnitude (deg)', 0, 360, 3),
    ('timeout_s', 'Batch timeout (s)', 2, 86400, 1),
]

CLEANUP_LEVELS = dict(CCD_EC=1, CCD_EA=0, MW_A=0, MW_C=0,
    AOMA=1, AOMC=1, AOMB=1, AOMM=1, EOM_7GA1=1, EOM_7GA2=1,
    EOM_7GC1=1, EOM_7GC2=1, EOM_2GA=0, EOM_2GC=0, TRIG=0)

def defaults():
    return dict(schema_version=1, basis='mw_detuned', batches=100,
        groups_per_loop=50000, inner_trials=10, fpga_loops=10,
        cooling_us=5., initialization_us=1., aom_off_us=.30, stopwatch_wait_us=.21,
        decay_lower_a=86, decay_lower_c=86, coincidence_half_window_bins=10,
        mirror_wait_ms=600., detection_us=100., threshold_ea=2, threshold_ec=2,
        pi_ea_us=81.10, pi_ec_us=70.58, detuning_hz=-2000.,
        phase_magnitude_deg=175., timeout_s=120.)

def nominal_trials(c):
    return c['groups_per_loop'] * c['inner_trials'] * c['fpga_loops']

def resolved_outputs(c=None):
    return {name: dict(pin=OUTPUTS[name][0], port=OUTPUTS[name][1], bit=OUTPUTS[name][2])
            for name in CLEANUP_LEVELS}

def validate(c):
    if not isinstance(c, dict) or set(c) != set(defaults()) or type(c['schema_version']) is not int or c['schema_version'] != 1:
        raise ValueError('Invalid entanglement settings schema')
    if c['basis'] not in ('zz', 'mw_detuned'):
        raise ValueError('Choose ZZ or MW detuned')
    for k, _, lo, hi, decimals in FIELDS:
        v = c[k]
        if type(v) not in (int, float) or not math.isfinite(v) or not lo <= v <= hi or (not decimals and type(v) is not int):
            raise ValueError('Invalid ' + k)
    for k in ('cooling_us', 'initialization_us', 'detection_us', 'aom_off_us', 'stopwatch_wait_us', 'pi_ea_us', 'pi_ec_us', 'mirror_wait_ms'):
        unit = .02 if k.startswith('pi_') else .5 if k == 'mirror_wait_ms' else .01
        if not math.isclose(c[k]/unit, round(c[k]/unit), abs_tol=1e-7, rel_tol=0):
            raise ValueError(f'{k} must be a multiple of {unit}')
    if c['timeout_s'] <= 2*c['mirror_wait_ms']/1000 + c['detection_us']/1e6 + 1:
        raise ValueError('Timeout must exceed mirror waits, detection and communication margin')
    for name, info in resolved_outputs().items():
        expected = hd.external_slow_port if name in ('CCD_EC','CCD_EA','AOMB','AOMM') else hd.external_control_port
        if info['port'] != expected:
            raise ValueError(name + ' is not on the port used by the reviewed sequence')
    pairs = [(v['port'],v['bit']) for v in resolved_outputs().values()]
    if len(set(pairs)) != len(pairs):
        raise ValueError('Entanglement output roles must use distinct vendor pins')
    if c['basis'] == 'mw_detuned':
        if c['detuning_hz'] == 0:
            raise ValueError('Nonzero detuning is required for MW phase-delay mode')
        a, b = round(c['pi_ea_us']*50), round(c['pi_ec_us']*50)
        gap = int(c['phase_magnitude_deg']/360/abs(c['detuning_hz'])*1e8)
        ticks = sorted(set((0, a, gap, gap+b)))
        if any(not 0 <= y-x-7 <= 65535 for x,y in zip(ticks,ticks[1:])):
            raise ValueError('MW edge interval cannot be represented (7-clock overhead / 16-bit wait)')
    return deepcopy(c)

def phase_values(c):
    """Timing-induced phase change; not an absolute calibrated measurement axis."""
    active = c['basis'] == 'mw_detuned'
    ticks = int(c['phase_magnitude_deg']/360/abs(c['detuning_hz'])*1e8) if active else None
    gap = ticks*.01 if active else None
    phase = 360*c['detuning_hz']*gap*1e-6 if active else None
    return dict(definition_version=2, reference='pulse_start',
        time_difference='EC half-pi start minus EA half-pi start',
        detuning_definition='f_MW - f_qubit (Hz)',
        phase_definition='EC - EA; timing-induced relative phase change',
        formula='360 * detuning_hz * start_gap_us * 1e-6',
        assumptions='Equal detunings and stable coherent MW relative phase; excludes path offset and finite-pulse measurement-axis correction',
        input_phase_magnitude_deg=c['phase_magnitude_deg'], detuning_hz=c['detuning_hz'],
        half_pi_ea_us=c['pi_ea_us']/2, half_pi_ec_us=c['pi_ec_us']/2,
        start_gap_ticks=ticks, sequencer_clock_ns=10, start_gap_us=gap,
        drive_phase_deg=phase, drive_phase_mod360_deg=phase % 360 if active else None)


def save_settings(path, c):
    c = validate(c)
    save(path, dict(document_type='entanglement_settings', settings=c, phase=phase_values(c)))


def load(path=None):
    p = Path(path or ROOT/'entanglement.local.json')
    if not p.exists() and path is None:
        return validate(defaults())
    document = read(p)
    if document.get('document_type') == 'entanglement_settings':
        document = document['settings']
    return validate(document)
