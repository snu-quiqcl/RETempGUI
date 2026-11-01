import math
from copy import deepcopy
from types import SimpleNamespace
from labremote.characterization.config import read,save
from labremote.config.paths import CONFIG_ROOT
from labremote.devices.fpga.controller import hd,OUTPUTS

ROOT=CONFIG_ROOT/'operations/decay'
MODES=('171_single','174_single','171_dual','174_dual')
LABELS={'171_single':'171','174_single':'174','171_dual':'171 Interferometer','174_dual':'174 Interferometer'}
INPUTS=tuple(n for n in hd.input_mapping.values() if hasattr(hd,n+'_stopwatch_result'))
FAST=tuple(n for n,(_,port,_) in OUTPUTS.items() if port==hd.external_control_port)
SLOW=('',)+tuple(n for n in ('AOMM','AOMB') if n in OUTPUTS)
CHOICES={'PMT1':INPUTS,'PMT2':INPUTS,'SYNC':INPUTS,'AOM':FAST,'TRIG':FAST,'EOM_7G1':FAST,'EOM_7G2':FAST,'EOM_2G':FAST,'AUX1':SLOW,'AUX2':SLOW}
FIELDS=[('TIME_COOL','Cooling (10 ns clocks)',0,65535),('TIME_INIT','Initialization / 174 AOM hold (clocks)',5,65535),
 ('waiting_time_for_AOM_off','AOM off wait (clocks)',3,65535),('waiting_time_for_AOM_on','AOM on wait (clocks; single only)',3,65535),
 ('waiting_time_for_stopwatch','Stopwatch wait (sequencer clocks)',4,65535),('MAX_TIME_DIFFERENCE','Histogram bins (multiple of 3)',3,510),
 ('SIGNAL_THRESHOLD','Acquisition lower bin',0,509),('DECAY_THRESHOLD','Decay / prompt boundary bin',0,509),
 ('run_number','Cooling groups / FPGA outer loop',1,65535),('outer_loop_in_fpga','FPGA outer loops / batch',1,65535),
 ('wo_cooling_number','Pulse trials / cooling group',1,65535),('outer_loop','PC batches',1,10000),
 ('timeout_s','Timeout / hardware chunk (s)',1,3600),('reference_tau_ns','Reference lifetime (ns; not fit)',.01,1000),
 ('aux1_start','AUX1 start level',0,1),('aux1_end','AUX1 cleanup level',0,1),('aux2_start','AUX2 start level',0,1),('aux2_end','AUX2 cleanup level',0,1)]

def defaults(chamber,mode):
    if chamber not in ('EA','EC') or mode not in MODES:raise ValueError('Invalid decay chamber/mode')
    dual=mode.endswith('dual');is171=mode.startswith('171');suffix='A' if chamber=='EA' else 'C'
    c=dict(schema_version=1,chamber=chamber,mode=mode,MAX_TIME_DIFFERENCE=102 if mode=='171_single' else 120,
        waiting_time_for_stopwatch=21 if dual else 20,waiting_time_for_AOM_off=30 if mode=='171_dual' else 20 if dual else 100 if is171 else 150,
        run_number=50000,outer_loop_in_fpga=2 if mode=='171_single' else 1,wo_cooling_number=10 if is171 else 1,
        outer_loop=500 if mode=='171_single' else 1000 if mode=='171_dual' else 100,
        TIME_COOL=500 if mode=='171_single' else 100 if mode=='174_dual' else 1000,
        TIME_INIT=100 if mode=='171_single' else 150 if is171 else 5 if dual else 50,
        SIGNAL_THRESHOLD=82 if mode=='171_dual' else 86 if mode=='174_dual' else 70,
        DECAY_THRESHOLD=85 if mode=='171_dual' else 86 if mode=='174_dual' else 70,
        timeout_s=120.,reference_tau_ns=8.12,aux1_start=1,aux1_end=1,aux2_start=1,aux2_end=1)
    c['waiting_time_for_AOM_on']=c['waiting_time_for_AOM_off']
    c['roles']=dict(PMT1='PMTA',PMT2='PMTC',SYNC='SYNC',AOM='AOM'+suffix,TRIG='TRIG',EOM_7G1='EOM_7G'+suffix+'1',EOM_7G2='EOM_7G'+suffix+'2',EOM_2G='EOM_2G'+suffix,AUX1='AOMM',AUX2='AOMB' if mode=='171_single' else '')
    return c

def validate(c):
    if not isinstance(c,dict) or c.get('chamber') not in ('EA','EC') or c.get('mode') not in MODES:raise ValueError('Invalid decay profile')
    if set(c)!=set(defaults(c['chamber'],c['mode'])) or c['schema_version']!=1:raise ValueError('Invalid decay schema')
    for key,_,lo,hi in FIELDS:
        v=c[key]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi or (key not in ('timeout_s','reference_tau_ns') and type(v) is not int):raise ValueError('Invalid '+key)
    if c['MAX_TIME_DIFFERENCE']%3:raise ValueError('Histogram bins must be a multiple of 3')
    if not 0<=c['SIGNAL_THRESHOLD']<=c['DECAY_THRESHOLD']<c['MAX_TIME_DIFFERENCE']:raise ValueError('Require acquisition lower bin <= decay boundary < histogram bins')
    r=c['roles']
    if not isinstance(r,dict) or set(r)!=set(CHOICES) or any(r[k] not in choices for k,choices in CHOICES.items()):raise ValueError('Invalid FPGA role mapping')
    inputs=[r['SYNC'],r['PMT1']]+([r['PMT2']] if c['mode'].endswith('dual') else [])
    if len(set(inputs))!=len(inputs):raise ValueError('PMT and SYNC inputs must be distinct')
    outputs=[r['AOM'],r['TRIG']]+([r[k] for k in ('EOM_7G1','EOM_7G2','EOM_2G')] if c['mode'].startswith('171') else [])+[r[k] for k in ('AUX1','AUX2') if r[k]]
    if len(set(outputs))!=len(outputs):raise ValueError('Active output roles must be distinct')
    return deepcopy(c)

def load(chamber,mode,path=None):
    local=ROOT/f'{chamber}_{mode}.local.json'
    c=validate(read(path or (local if local.exists() else ROOT/f'{chamber}_{mode}.json')))
    if (c['chamber'],c['mode'])!=(chamber,mode):raise ValueError('Profile differs from this tab')
    return c

def hardware(c):
    h=SimpleNamespace(external_control_port=hd.external_control_port,Trigger_level=hd.Trigger_level)
    for role in ('PMT1','PMT2','SYNC'):
        for suffix in ('stopwatch_result','stopwatch_start','stopwatch_reset','stopwatch_stopped_TLI'):
            setattr(h,role+'_'+suffix,getattr(hd,c['roles'][role]+'_'+suffix))
    for role in ('AOM','TRIG','EOM_7G1','EOM_7G2','EOM_2G'):setattr(h,role+'_out',OUTPUTS[c['roles'][role]][2])
    return h

def set_auxiliary(program,c,*,start):
    for i in (1,2):
        name=c['roles']['AUX'+str(i)]
        if name:
            _,port,bit=OUTPUTS[name];program.set_output_port(port,[(bit,c[f'aux{i}_'+('start' if start else 'end')])])
