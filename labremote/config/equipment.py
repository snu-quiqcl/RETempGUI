"""Equipment selection only. Never changes per-device settings or performs I/O."""
import json
import os
from copy import deepcopy
from pathlib import Path
from .paths import CONFIG_ROOT

LOCAL=CONFIG_ROOT/'ui/equipment.local.json'
GROUPS=('RF','미라','CCD','FPGA','오실로스코프','기타')
FAMILY_GROUP={'windfreak':'RF','sg384':'RF','anapico':'RF','dds4':'RF','thermotek':'미라','osa':'미라','mdt':'미라','ccd':'CCD','fpga':'FPGA','ds1052e':'오실로스코프','mso7054':'오실로스코프','keithley':'기타','motors':'기타','flip':'기타','oven_psu':'기타','oven_relay':'기타'}
SINGLETONS={'ccd','oven_psu','oven_relay'}

def validate(document):
    if not isinstance(document,dict) or not {'schema_version','name','devices'} <= set(document) or set(document)-{'schema_version','name','devices','ccd_display'} or type(document['schema_version']) is not int or document['schema_version']!=1:
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
    display_config(document.get('ccd_display', {}))
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
    template=load(CONFIG_ROOT/'ui/equipment.json')
    devices=list(template['devices'])
    for family,group in FAMILY_GROUP.items():
        if family in ('ccd','flip','oven_psu','oven_relay'):continue
        for name in dict.fromkeys((*configured_instrument_names(family),*cfg.get(family+'_names',[]))):
            if not any(d['family']==family and d['name']==name for d in devices):
                devices.append(dict(family=family,name=name,group=group,enabled=True))
    template['devices']=devices
    return validate(template)


DISPLAY_DEFAULTS = dict(auto_levels=True, low=0, high=4095, flip_h=False,
                        flip_v=False, markers_enabled=True, color='grey')

def display_config(options):
    if not isinstance(options,dict) or set(options)-set(DISPLAY_DEFAULTS):
        raise ValueError('Invalid CCD display settings')
    cfg={**DISPLAY_DEFAULTS,**options}
    for key in ('auto_levels','flip_h','flip_v','markers_enabled'):
        if type(cfg[key]) is not bool:raise ValueError(key+' must be boolean')
    if any(type(cfg[k]) is not int or not 0<=cfg[k]<=65535 for k in ('low','high')) or cfg['low']>=cfg['high']:
        raise ValueError('CCD display levels need 0 <= low < high <= 65535')
    if cfg['color'] not in ('grey','viridis','inferno'):raise ValueError('Invalid CCD colormap')
    return cfg
