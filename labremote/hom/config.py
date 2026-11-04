"""Validated HOM profiles. Times are stored as sequencer clocks, not ns bins."""
import math
import re
from copy import deepcopy
from types import SimpleNamespace
from labremote.characterization.config import read, save
from labremote.config.paths import CONFIG_ROOT
from labremote.devices.fpga.controller import hd

ROOT = CONFIG_ROOT / 'operations/hom'
CLOCK_US = .01
BIN_NS = 1.25
INPUTS = tuple(n for n in hd.input_mapping.values() if hasattr(hd, n+'_stopwatch_result'))
PINS = {n[:-4]: (hd.external_slow_port if n.startswith(('jc_', 'jd_')) else hd.external_control_port, getattr(hd,n))
        for n in vars(hd) if re.fullmatch(r'j[abcd]_[0-7]_out',n)}
TIMES = {'TIME_1US', 'waiting_time_for_AOM_off', 'waiting_time_for_stopwatch'}
FIELDS = [
 ('TIME_1US','Group cooling (µs)',5,65535),
 ('waiting_time_for_AOM_off','AOM OFF wait / trial (µs)',3,65535),
 ('waiting_time_for_stopwatch','Stopwatch wait (µs)',4,65535),
 ('THRESHOLD_A','PMTA lower bin',0,254), ('THRESHOLD_C','PMTC lower bin',0,254),
 ('MAX_TIME_DIFFERENCE','Histogram M (multiple of 3)',3,255),
 ('run_number','Cooling groups / FPGA loop',1,65535),
 ('inner_loop_number','Trials / group',1,65535),
 ('outer_loop_in_fpga','FPGA loops / batch',1,65535),
 ('outer_loop','Batches / block',1,10000), ('outer_outer_loop','Blocks',1,10000),
 ('timeout_s','Batch timeout (s)',1,3600),
 ('aomb_start','AOMB acquisition level',0,1), ('aomb_end','AOMB cleanup level',0,1)]

def defaults():
    return dict(schema_version=1,TIME_1US=150,waiting_time_for_AOM_off=25,
        waiting_time_for_stopwatch=25,THRESHOLD_A=86,THRESHOLD_C=86,MAX_TIME_DIFFERENCE=120,
        run_number=50000,inner_loop_number=2,outer_loop_in_fpga=100,outer_loop=50,
        outer_outer_loop=10,timeout_s=120.,aomb_enabled=True,aomb_start=1,aomb_end=1,
        inputs=dict(PMTA='PMTA',PMTC='PMTC',SYNC='SYNC'),
        outputs={name:dict(pin=pin,port=PINS[pin][0]) for name,pin in
                 [('AOMA','ja_5'),('AOMC','ja_3'),('TRIG','ja_4'),('AOMB','jc_1')]})

def nominal_trials(c):
    return c['run_number']*c['inner_loop_number']*c['outer_loop_in_fpga']

def validate(c):
    if not isinstance(c,dict) or set(c)!=set(defaults()) or type(c['schema_version']) is not int or c['schema_version']!=1:
        raise ValueError('Invalid HOM settings schema')
    for k,_,lo,hi in FIELDS:
        v=c[k]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi or (k!='timeout_s' and type(v) is not int):
            raise ValueError('Invalid '+k)
    m=c['MAX_TIME_DIFFERENCE']
    if m%3 or 4*m>1024:raise ValueError('M must be a multiple of 3, maximum 255')
    if max(c['THRESHOLD_A'],c['THRESHOLD_C'])>=m:raise ValueError('PMT lower bins must be smaller than M')
    if type(c['aomb_enabled']) is not bool:raise ValueError('AOMB enabled must be boolean')
    r=c['inputs']
    if not isinstance(r,dict) or set(r)!={'PMTA','PMTC','SYNC'} or any(v not in INPUTS for v in r.values()) or len(set(r.values()))!=3:
        raise ValueError('Choose three distinct stopwatch inputs')
    out=c['outputs']
    if not isinstance(out,dict) or set(out)!={'AOMA','AOMC','TRIG','AOMB'}:raise ValueError('Invalid HOM output mapping')
    active=[]
    for role,v in out.items():
        if not isinstance(v,dict) or set(v)!={'pin','port'} or v['pin'] not in PINS or type(v['port']) is not int or v['port']!=PINS[v['pin']][0]:
            raise ValueError('Pin/port mismatch: '+role)
        if role!='AOMB' and v['port']!=hd.external_control_port:raise ValueError(role+' needs the fast output port')
        if role!='AOMB' or c['aomb_enabled']:active.append((v['port'],PINS[v['pin']][1]))
    if len(set(active))!=len(active):raise ValueError('Active output pins must be distinct')
    return deepcopy(c)

def load(path=None):
    p=path or ROOT/'hom.local.json'
    from pathlib import Path
    return validate(read(p)) if Path(p).exists() else (validate(defaults()) if path is None else read(p))

def from_display(key,value):
    if key not in TIMES:return value
    clocks=round(value/CLOCK_US)
    if not math.isclose(value,clocks*CLOCK_US,abs_tol=1e-9,rel_tol=0):raise ValueError('Times must be multiples of 0.01 µs')
    return clocks

def hardware(c):
    h=SimpleNamespace(Trigger_level=hd.Trigger_level)
    for role,name in c['inputs'].items():
        for suffix in ('stopwatch_result','stopwatch_start','stopwatch_reset','stopwatch_stopped_TLI'):
            setattr(h,role+'_'+suffix,getattr(hd,name+'_'+suffix))
    return h

def outputs(s,c,levels):
    ports={}
    for role,level in levels.items():
        port,bit=PINS[c['outputs'][role]['pin']]
        ports.setdefault(port,[]).append((bit,level))
    first=None
    for port,pins in sorted(ports.items()):
        instruction=s.set_output_port(port,pins)
        if first is None:first=instruction
    return first

def auxiliary(s,c,start):
    if c['aomb_enabled']:outputs(s,c,{'AOMB':c['aomb_start' if start else 'aomb_end']})
