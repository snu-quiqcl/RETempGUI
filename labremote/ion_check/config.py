from labremote.devices.fpga.mapping import settings_path
from copy import deepcopy
import math
from labremote.config.paths import CONFIG_ROOT
from labremote.characterization.config import read, save
from labremote.devices.fpga.controller import hd,OUTPUTS

ROOT=CONFIG_ROOT/'operations/ion_check'
PMT_CHOICES=tuple(name for name in hd.input_mapping.values() if name.startswith('PMT') and all(hasattr(hd,name+suffix) for suffix in ('_counter_enable','_counter_reset','_counter_result')))
LASER_CHOICES=tuple(name for name in OUTPUTS if name.startswith('AOM'))

def default_mapping():
    return dict(pmt_1='PMTA',pmt_2='PMTC',laser_a='AOMA',laser_b='AOMB',laser_c='AOMC')

def validate_mapping(value):
    if not isinstance(value,dict) or set(value)!=set(default_mapping()):raise ValueError('Invalid Ion Check channel mapping')
    if value['pmt_1'] not in PMT_CHOICES or value['pmt_2'] not in (None,*PMT_CHOICES):raise ValueError('Select supported PMT inputs')
    if value['pmt_1']==value['pmt_2']:raise ValueError('PMT 1과 PMT 2는 서로 다른 입력을 선택하세요.')
    if value['pmt_2'] is not None and getattr(hd,value['pmt_1']+'_counter_result') == getattr(hd,value['pmt_2']+'_counter_result'):
        raise ValueError('PMT roles resolve to the same physical input')
    lasers=[value['laser_'+k] for k in 'abc']
    if any(v not in LASER_CHOICES for v in lasers) or len(set(lasers))!=3:raise ValueError('Laser A/B/C는 서로 다른 AOM 출력을 선택하세요.')
    if len({OUTPUTS[name][1:] for name in lasers}) != 3:raise ValueError('Laser roles resolve to duplicate physical outputs')
    return deepcopy(value)

def pmt_names(c):return [c.get('mapping',default_mapping())[key] for key in ('pmt_1','pmt_2') if c.get('mapping',default_mapping())[key] is not None]

def output_levels(c,a=1,b=0,d=1):
    mapping=c.get('mapping',default_mapping())
    return {mapping['laser_a']:a,mapping['laser_b']:b,mapping['laser_c']:d,
            'EOM_7GA1':a,'EOM_7GA2':a,'EOM_7GC1':d,'EOM_7GC2':d,
            'EOM_2GA':0,'EOM_2GC':0,'MW_A':0,'MW_C':0}

def defaults():
    return dict(schema_version=2,mapping=default_mapping(),exposure_us=1000,settle_us=100,
                threshold_a=None,threshold_b=None,threshold_c=None,
                max_attempts=3,retry_delay_s=.1,timeout_s=5.)

def validate(value,require_thresholds=False):
    value=deepcopy(value)
    if isinstance(value,dict) and type(value.get('schema_version')) is int and value['schema_version']==1 and set(value)==set(defaults())-{'mapping'}:
        value.update(schema_version=2,mapping=default_mapping())
    if not isinstance(value,dict) or set(value)!=set(defaults()) or type(value['schema_version']) is not int or value['schema_version']!=2:
        raise ValueError('Invalid Ion Check settings schema')
    value['mapping']=validate_mapping(value['mapping'])
    for key in ('exposure_us','settle_us','max_attempts'):
        if type(value[key]) is not int or not 1<=value[key]<=10000:raise ValueError(key+' must be 1..10000')
    for key,lo,hi in [('retry_delay_s',0,3600),('timeout_s',.1,600)]:
        v=value[key]
        if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Invalid '+key)
    for key in ('threshold_a','threshold_b','threshold_c'):
        v=value[key]
        if v is None and not require_thresholds:continue
        if type(v) is not int or not 1<=v<=65535:raise ValueError(key+'를 1..65535 범위로 입력하세요.')
    if value['timeout_s']<=3*(value['settle_us']+value['exposure_us'])/1e6:
        raise ValueError('Timeout must exceed the sequence exposure/settling duration')
    return deepcopy(value)

def load(path=None):
    path=path or settings_path(ROOT/'ion_check.local.json')
    from pathlib import Path
    if not Path(path).exists():
        if Path(path)==settings_path(ROOT/'ion_check.local.json'):return defaults()
        raise FileNotFoundError(path)
    return validate(read(path))

def classify(counts,c):
    thresholds=[c['threshold_'+k] for k in 'abc']
    if any(v is None for v in thresholds):return 'unconfigured',dict.fromkeys('abc')
    a,b,d=[count>=threshold for count,threshold in zip(counts,thresholds)]
    if not b and a and d:decision='normal'
    elif b:decision='swap_ea_then_ec' if not a and not d else 'swap_ea' if not a else 'swap_ec' if not d else 'recheck'
    else:decision='ion_loss_suspected'
    return decision,dict(zip('abc',(a,b,d)))

LABELS={'normal':'정상 · 실험 진행 가능','swap_ea':'EA swap 후보',
        'swap_ec':'EC swap 후보','swap_ea_then_ec':'EA → EC swap 후보',
        'recheck':'불명확 · 재측정 필요','ion_loss_suspected':'Ion loss 의심',
        'unconfigured':'판정 대기 · threshold 미설정'}
