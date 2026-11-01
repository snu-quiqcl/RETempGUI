"""Equipment selection only. Never changes per-device settings or performs I/O."""
import json
import os
from copy import deepcopy
from pathlib import Path
from .paths import CONFIG_ROOT

LOCAL=CONFIG_ROOT/'equipment.local.json'
GROUPS=('RF','미라','CCD','FPGA','오실로스코프','기타')
FAMILY_GROUP={'windfreak':'RF','sg384':'RF','anapico':'RF','dds4':'RF','thermotek':'미라','osa':'미라','mdt':'미라','ccd':'CCD','fpga':'FPGA','ds1052e':'오실로스코프','mso7054':'오실로스코프','keithley':'기타','motors':'기타','flip':'기타','oven_psu':'기타','oven_relay':'기타'}
SINGLETONS={'ccd','oven_psu','oven_relay'}

def validate(document):
    if not isinstance(document,dict) or set(document)!={'schema_version','name','devices'} or type(document['schema_version']) is not int or document['schema_version']!=1:
        raise ValueError('Expected equipment schema_version 1, name and devices')
    if not isinstance(document['name'],str) or not document['name'].strip():raise ValueError('Configuration name is required')
    if not isinstance(document['devices'],list) or len(document['devices'])>512:raise ValueError('Invalid equipment list (maximum 512)')
    seen=set();single=set()
    for item in document['devices']:
        if not isinstance(item,dict) or set(item)!={'family','name','group','enabled'}:raise ValueError('Each device needs family, name, group and enabled')
        family=item['family'];name=item['name']
        if not isinstance(family,str) or family not in FAMILY_GROUP or not isinstance(name,str) or not name.isidentifier():raise ValueError('Invalid device family / instrument name')
        if item['group'] not in GROUPS or type(item['enabled']) is not bool:raise ValueError('Invalid group / enabled value')
        key=(family,name)
        if key in seen:raise ValueError('Duplicate equipment: '+name)
        seen.add(key)
        if family in SINGLETONS:
            if family in single:raise ValueError('Only one '+family+' entry is supported')
            single.add(family)
        if family=='ccd' and name!='ccd_local':raise ValueError('Local CCD name must be ccd_local')
    return deepcopy(document)

def load(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8-sig')))

def save(path,document):
    data=validate(document);path=Path(path)
    if not path.name.endswith('.local.json'):
        raise ValueError('Save personal equipment configurations as *.local.json (excluded from Git)')
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(temp,path)

def defaults(cfg):
    from .device_config import configured_instrument_names
    devices=[]
    for family,group in FAMILY_GROUP.items():
        if family in ('ccd','flip','oven_psu','oven_relay'):continue
        for name in dict.fromkeys((*configured_instrument_names(family),*cfg.get(family+'_names',[]))):
            devices.append(dict(family=family,name=name,group=group,enabled=True))
    devices.extend([dict(family='ccd',name='ccd_local',group='CCD',enabled=True),dict(family='oven_psu',name='oven_psu',group='기타',enabled=False),dict(family='oven_relay',name='oven_relays',group='기타',enabled=False)])
    return validate(dict(schema_version=1,name='기본 실험 구성',devices=devices))
