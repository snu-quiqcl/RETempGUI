import json
from labremote.devices.fpga.mapping import EDITING
import math
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
import numpy as np
from labremote.devices.fpga.mapping import hd, settings_path, resolve_signal, role_signal_token
from labremote.micromotion.config import PINS, STOPWATCH_PINS, COUNTER_PINS
from .model import _geometry, _fit_first_event

from labremote.configuration.paths import CONFIG_ROOT
ROOT=CONFIG_ROOT/'operations/micromotion'
FLOATS={'start_khz':(50,5000),'stop_khz':(50,5000),'step_khz':(.001,4950),
        'amplitude_dbm':(-56.020599,23.9794),'offset_v':(-5,5),'settle_s':(0,60),
        'point_timeout_s':(1,3600),'max_background_m':(0,1)}
INTS={'phase_bins':(8,256),'target_events':(64,5000000),'max_attempts':(64,50000000),
      'block_attempts':(1,60000),'count_exposure_us':(1,10000),'count_repeats':(2,1000)}


def defaults(chamber='EC'):
    from labremote.configuration.default_profiles import read_default
    return read_default('secular_'+chamber)


def frequencies(c):
    start,stop,step=(Decimal(str(c[k])) for k in ('start_khz','stop_khz','step_khz'))
    if not all(v.is_finite() for v in (start,stop,step)) or step<=0 or stop<start:
        raise ValueError('Frequency scan requires finite start <= stop and step > 0')
    count=int(((stop-start)/step).to_integral_value(rounding=ROUND_FLOOR))+1
    if not 1<=count<=10000:raise ValueError('Scan is limited to 10000 frequencies')
    return [float(start+i*step) for i in range(count)]


def validate(settings):
    c=dict(settings)
    if c.get('schema_version')!=1 or c.get('chamber') not in ('EA','EC'):
        raise ValueError('Invalid secular scan schema/chamber')
    for k,(lo,hi) in FLOATS.items():
        if isinstance(c.get(k),bool):raise ValueError(k+' must be numeric')
        c[k]=float(c[k])
        if not math.isfinite(c[k]) or not lo<=c[k]<=hi:raise ValueError(f'{k}: expected {lo}..{hi}')
    for k,(lo,hi) in INTS.items():
        if type(c.get(k)) is not int or not lo<=c[k]<=hi:raise ValueError(f'{k}: expected integer {lo}..{hi}')
    if c.get('rate_action') not in ('stop','warn'):raise ValueError('Unknown rate limit action')
    if not isinstance(c.get('afg_name',''),str):raise ValueError('Invalid source name')
    if not EDITING.get():
        pins = {k: resolve_signal(c.get(k)) for k in ('trg_pin','pmt_pin')}
        if pins['trg_pin'] not in STOPWATCH_PINS or pins['pmt_pin'] not in STOPWATCH_PINS:
            raise ValueError('SYNC and PMT require stopwatch inputs')
        if pins['trg_pin']==pins['pmt_pin']:raise ValueError('SYNC and PMT must be different inputs')
        if pins['pmt_pin'] not in COUNTER_PINS:raise ValueError('PMT input must support count AND stopwatch')
    if c['target_events']>c['max_attempts']:raise ValueError('Target events must not exceed maximum attempts')
    if c['target_events']<c['phase_bins']:raise ValueError('Target events must be at least the phase-bin count')
    _geometry(max(frequencies(c)),c['phase_bins'])
    if abs(c['offset_v'])+math.sqrt(0.1*10**(c['amplitude_dbm']/10))>5:
        raise ValueError('Source sine peak plus |offset| exceeds 5 V at 50 ohms')
    return c


def hardware(c):
    def timing(pin):
        name=PINS[pin]
        return {key:getattr(hd,name+'_stopwatch_'+suffix) for key,suffix in
                [('reset','reset'),('start','start'),('result','result'),('stopped_tli','stopped_TLI')]}
    pmt=timing(c['pmt_pin']);pmt['trigger_level']=hd.Trigger_level
    name=PINS[c['pmt_pin']]
    count={key:getattr(hd,name+'_counter_'+suffix) for key,suffix in
           [('reset','reset'),('enable','enable'),('result','result')]}
    count['control_port']=hd.counter_control_port
    return dict(pmts=[dict(timing=pmt,count=count)],signals={'modulation_sync':timing(c['trg_pin'])})


def clean(value):
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    return value


def fit(histogram,frequency_khz,rate,sem):
    result=_fit_first_event(histogram,frequency_khz,rate,sem)
    values=result['values'];errors=result['errors']
    result.update(modulation=values[3],modulation_se=errors[3],phase_rad=values[4],phase_se=errors[4])
    return clean(result)


def settings_file(chamber):return settings_path(ROOT/(chamber+'.secular.json'))


def load(chamber):
    path=settings_file(chamber)
    return validate(__import__('labremote.configuration.experiment_settings',fromlist=['read']).read(path)) if path.exists() else defaults(chamber)
