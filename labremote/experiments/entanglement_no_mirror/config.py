from labremote.devices.fpga.mapping import settings_path
"""Editable experiment parameters; hardware names come only from vendor definitions."""
from labremote.devices.fpga.mapping import EDITING
import math
from copy import deepcopy
from pathlib import Path
from labremote.experiments.characterization.shared.config import read, save
from labremote.configuration.paths import CONFIG_ROOT
from labremote.devices.fpga.controller import hd, OUTPUTS

ROOT = CONFIG_ROOT / 'operations/entanglement_no_mirror'
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
    ('detection_ea_us', 'EA state detection (µs)', .01, 655.35, 2),
    ('detection_ec_us', 'EC state detection (µs)', .01, 655.35, 2),
    ('threshold_ea', 'EA bright threshold: PMT1 + PMT2 >', 0, 131070, 0),
    ('threshold_ec', 'EC bright threshold: PMT1 + PMT2 >', 0, 131070, 0),
    ('pi_ea_us', 'EA resonant π time (µs)', .14, 1310.84, 2),
    ('pi_ec_us', 'EC resonant π time (µs)', .14, 1310.84, 2),
    ('detuning_hz', 'Detuning (Hz) — timing only', -10000000, 10000000, 2),
    ('phase_magnitude_deg', 'Start-phase magnitude (deg)', 0, 360, 3),
    ('timeout_s', 'Batch timeout (s)', 2, 86400, 1),
]

CLEANUP_LEVELS = dict(MW_A=0, MW_C=0,
    AOMA=1, AOMC=1, AOMB=1, AOMM=1, EOM_7GA1=1, EOM_7GA2=1,
    EOM_7GC1=1, EOM_7GC2=1, EOM_2GA=0, EOM_2GC=0, TRIG=0)

def defaults():
    from labremote.configuration.default_profiles import read_default
    return read_default('entanglement_no_mirror')

def nominal_trials(c):
    return c['groups_per_loop'] * c['inner_trials'] * c['fpga_loops']

def resolved_outputs(c=None):
    return {name: dict(pin=OUTPUTS[name][0], port=OUTPUTS[name][1], bit=OUTPUTS[name][2])
            for name in CLEANUP_LEVELS}

from labremote.devices.fpga.routing import scoped
@scoped('entanglement_no_mirror')
def validate(c):
    if not EDITING.get():
        for roles, suffix in [(('PMTA','PMTC','SYNC'),'_stopwatch_result'), (('PMTFA','PMTFC'),'_counter_result')]:
            if len({getattr(hd, role+suffix) for role in roles}) != len(roles):
                raise ValueError('Entanglement input roles must resolve to distinct physical inputs')
    if not isinstance(c, dict) or set(c)-{'fpga_mapping'} != set(defaults())-{'fpga_mapping'} or type(c['schema_version']) is not int or c['schema_version'] != 1:
        raise ValueError('Invalid entanglement settings schema')
    if c.get('experiment')!='entanglement_no_mirror':raise ValueError('Expected RE without flip mirror settings')
    if c['basis'] not in ('zz', 'mw_detuned'):
        raise ValueError('Choose ZZ or MW detuned')
    for k, _, lo, hi, decimals in FIELDS:
        v = c[k]
        if type(v) not in (int, float) or not math.isfinite(v) or not lo <= v <= hi or (not decimals and type(v) is not int):
            raise ValueError('Invalid ' + k)
    for k in ('cooling_us', 'initialization_us', 'detection_ea_us', 'detection_ec_us', 'aom_off_us', 'stopwatch_wait_us', 'pi_ea_us', 'pi_ec_us'):
        unit = .02 if k.startswith('pi_') else .01
        if not math.isclose(c[k]/unit, round(c[k]/unit), abs_tol=1e-7, rel_tol=0):
            raise ValueError(f'{k} must be a multiple of {unit}')
    if c['timeout_s'] <= (c['detection_ea_us']+c['detection_ec_us']+2*c['aom_off_us'])/1e6 + 1:
        raise ValueError('Timeout must exceed both detections, AOM waits and communication margin')
    if not EDITING.get():
        for name, info in resolved_outputs().items():
            expected = hd.external_slow_port if name in ('AOMB','AOMM','MW_A','MW_C') else hd.external_control_port
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

# The MW basis definition is identical for both readout geometries.
from labremote.experiments.entanglement.config import phase_values


def save_settings(path, c):
    c = validate(c)
    save(path, dict(document_type='entanglement_settings', settings=c, phase=phase_values(c)))


def load(path=None):
    p = Path(path or settings_path(ROOT/'entanglement_no_mirror.json'))
    if not p.exists() and path is None:
        return validate(defaults())
    document = read(p)
    if document.get('document_type') == 'entanglement_settings':
        document = document['settings']
    return validate(document)
