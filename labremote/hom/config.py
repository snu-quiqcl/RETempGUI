from labremote.devices.fpga.mapping import settings_path
"""Validated HOM profiles. Times are stored as sequencer clocks, not ns bins."""
import math
from copy import deepcopy
from types import SimpleNamespace
from labremote.characterization.config import read, save
from labremote.config.paths import CONFIG_ROOT
from labremote.devices.fpga.controller import hd, OUTPUTS

ROOT = CONFIG_ROOT / 'operations/hom'
CLOCK_US = .01
BIN_NS = 1.25
INPUTS = tuple(n for n in hd.input_mapping.values() if hasattr(hd, n+'_stopwatch_result'))
TIMES = {'TIME_1US', 'waiting_time_for_AOM_off', 'waiting_time_for_stopwatch'}
FIELDS = [
 ('TIME_1US','Group cooling (µs)',5,65535),
 ('waiting_time_for_AOM_off','AOM OFF wait / trial (µs)',3,65535),
 ('waiting_time_for_stopwatch','Stopwatch wait (µs)',4,65535),
 ('THRESHOLD_A','PMTA lower bin',0,254), ('THRESHOLD_C','PMTC lower bin',0,254),
 ('MAX_TIME_DIFFERENCE','Histogram M (multiple of 3)',3,255),
 ('run_number','Cooling groups / FPGA loop',1,65535),
 ('inner_loop_number','Inner trials / group',1,65535),
 ('outer_loop_in_fpga','Group-loop repeats / batch',1,65535),
 ('batches','Batches',1,100000000),
 ('timeout_s','Batch timeout (s)',1,3600),
 ('aomb_start','AOMB acquisition level',0,1), ('aomb_end','AOMB cleanup level',0,1)]

def defaults():
    return dict(schema_version=2,TIME_1US=150,waiting_time_for_AOM_off=25,
        waiting_time_for_stopwatch=25,THRESHOLD_A=86,THRESHOLD_C=86,MAX_TIME_DIFFERENCE=120,
        run_number=50000,inner_loop_number=2,outer_loop_in_fpga=100,batches=500,
        timeout_s=120.,aomb_enabled=True,aomb_start=1,aomb_end=1,
        inputs=dict(PMTA='PMTA',PMTC='PMTC',SYNC='SYNC'),
        outputs={name:name for name in ('AOMA','AOMC','TRIG','AOMB')})


def nominal_trials(c):
    return c['run_number']*c['inner_loop_number']*c['outer_loop_in_fpga']

def migrate(c):
    c=deepcopy(c)
    if isinstance(c,dict) and type(c.get('schema_version')) is int and c['schema_version']==1:
        for key in ('outer_loop','outer_outer_loop'):
            if type(c.get(key)) is not int or not 1<=c[key]<=10000:raise ValueError('Invalid legacy '+key)
        c['batches']=c.pop('outer_loop')*c.pop('outer_outer_loop')
        resolved={}
        for role,v in c.get('outputs',{}).items():
            if not isinstance(v,dict) or set(v)!={'pin','port'} or type(v['port']) is not int:raise ValueError('Invalid legacy output')
            matches=[name for name,(pin,port,bit) in OUTPUTS.items() if pin==v['pin'] and port==v['port']]
            if role in matches:resolved[role]=role
            elif len(matches)==1:resolved[role]=matches[0]
            else:raise ValueError('Legacy output has no unique vendor alias: '+role+'; define it in vendor and reselect')
        c['outputs']=resolved; c['schema_version']=2
    return c


def resolved_outputs(c):
    return {role:dict(name=name,pin=OUTPUTS[name][0],port=OUTPUTS[name][1],bit=OUTPUTS[name][2]) for role,name in c['outputs'].items()}


def validate(c):
    c=migrate(c)
    if not isinstance(c,dict) or set(c)!=set(defaults()) or type(c['schema_version']) is not int or c['schema_version']!=2:
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
    if len({getattr(hd, name+'_stopwatch_result') for name in r.values()}) != 3:
        raise ValueError('HOM input roles resolve to the same physical pin')
    out=c['outputs']
    if not isinstance(out,dict) or set(out)!={'AOMA','AOMC','TRIG','AOMB'}:raise ValueError('Invalid HOM output mapping')
    active=[]
    for role,name in out.items():
        if not isinstance(name,str) or name not in OUTPUTS:raise ValueError('Unknown vendor output: '+role)
        pin,port,bit=OUTPUTS[name]
        if role!='AOMB' and port!=hd.external_control_port:raise ValueError(role+' needs the fast output port')
        if role!='AOMB' or c['aomb_enabled']:active.append((port,bit))
    if len(set(active))!=len(active):raise ValueError('Active output pins must be distinct')
    return deepcopy(c)

def load(path=None):
    p=path or settings_path(ROOT/'hom.local.json')
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
        _,port,bit=OUTPUTS[c['outputs'][role]]
        ports.setdefault(port,[]).append((bit,level))
    first=None
    for port,pins in sorted(ports.items()):
        instruction=s.set_output_port(port,pins)
        if first is None:first=instruction
    return first

def auxiliary(s,c,start):
    if c['aomb_enabled']:outputs(s,c,{'AOMB':c['aomb_start' if start else 'aomb_end']})
