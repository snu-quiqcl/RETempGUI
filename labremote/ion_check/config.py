from copy import deepcopy
import math
from labremote.config.paths import CONFIG_ROOT
from labremote.characterization.config import read, save

ROOT=CONFIG_ROOT/'operations/ion_check'

def defaults():
    return dict(schema_version=1,exposure_us=1000,settle_us=100,
                threshold_a=None,threshold_b=None,threshold_c=None,
                max_attempts=3,retry_delay_s=.1,timeout_s=5.)

def validate(value,require_thresholds=False):
    if not isinstance(value,dict) or set(value)!=set(defaults()) or type(value['schema_version']) is not int or value['schema_version']!=1:
        raise ValueError('Invalid Ion Check settings schema')
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
    path=path or ROOT/'ion_check.local.json'
    from pathlib import Path
    if not Path(path).exists():
        if Path(path)==ROOT/'ion_check.local.json':return defaults()
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
