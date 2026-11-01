import json
import math
from copy import deepcopy
from pathlib import Path
from labremote.config.paths import CONFIG_ROOT
from labremote.devices.fpga.controller import hd, INPUTS

ROOT=CONFIG_ROOT/'operations/characterization'
PMTS=tuple(name for name,_ in INPUTS.values() if name.startswith('PMT'))
AOMS=('AOMA','AOMC')


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8');temp.replace(path)


def validate_settings(value):
    if not isinstance(value,dict):raise ValueError('Expected fluorescence settings object')
    keys={'schema_version','chamber','exposure_ms','num_average','num_repeat','timeout_s'}
    if set(value)-{'roles'}!=keys or value['schema_version']!=1 or value['chamber'] not in ('EA','EC'):raise ValueError('Invalid fluorescence schema/chamber/fields')
    for key in ('num_average','num_repeat'):
        if type(value[key]) is not int or not 1<=value[key]<=65535:raise ValueError(key+' must be an integer in 1..65535')
    if 'roles' in value: validate_route(value['roles'])
    total=value['num_average']*value['num_repeat']
    if not 3<=total<=1000000:raise ValueError('Total samples must be 3..1000000')
    for key,lo,hi in (('exposure_ms',.1,6000),('timeout_s',.1,3600)):
        v=value[key]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Invalid '+key)
    if not math.isclose(value['exposure_ms']*10,round(value['exposure_ms']*10),abs_tol=1e-8):raise ValueError('Exposure must be a multiple of 0.1 ms')
    if value['timeout_s']<=value['exposure_ms']*value['num_average']/1000:raise ValueError('Per-batch timeout must exceed nominal acquisition time')
    return deepcopy(value)


def validate_route(route):
    if not isinstance(route,dict) or set(route)!={'PMT','AOM'} or route['PMT'] not in PMTS or route['AOM'] not in AOMS:
        raise ValueError('Select a supported PMT and AOMA/AOMC')
    return deepcopy(route)


def validate_roles(value):
    if not isinstance(value,dict) or value.get('schema_version')!=1 or value.get('setup')!='EC':raise ValueError('Expected EC setup mapping schema 1')
    if set(value.get('routes',{}))!={'EA','EC'}:raise ValueError('Both EA and EC mappings are required')
    for route in value['routes'].values():
        if not isinstance(route,dict) or set(route)!={'PMT','AOM'} or route['PMT'] not in PMTS or route['AOM'] not in AOMS:raise ValueError('Select a supported PMT and AOMA/AOMC')
    return deepcopy(value)


def load_settings(chamber,path=None):
    if chamber not in ('EA','EC'):raise ValueError('Select EA or EC')
    local=ROOT/f'fluorescence_{chamber}.local.json'
    value=validate_settings(read(path or (local if local.exists() else ROOT/f'fluorescence_{chamber}.json')))
    if value['chamber']!=chamber:raise ValueError('Settings chamber does not match this tab')
    if 'roles' not in value:value['roles']=load_roles()['routes'][chamber]
    return value


def load_roles(path=None):
    local=ROOT/'fpga_roles.local.json'
    return validate_roles(read(path or (local if local.exists() else ROOT/'fpga_roles.json')))


def sequence_hardware(route):
    """Resolve sequence aliases without modifying the shared HardwareDefinition."""
    from types import SimpleNamespace
    if route.get('PMT') not in PMTS or route.get('AOM') not in AOMS:raise ValueError('Invalid sequence role mapping')
    return SimpleNamespace(PMT_counter_reset=getattr(hd,route['PMT']+'_counter_reset'),
        PMT_counter_enable=getattr(hd,route['PMT']+'_counter_enable'),
        PMT_counter_result=getattr(hd,route['PMT']+'_counter_result'),
        AOM_out=getattr(hd,route['AOM']+'_out'),counter_control_port=hd.counter_control_port,
        external_control_port=hd.external_control_port)


def prepare(chamber,settings=None,settings_file=None,mapping_file=None):
    if settings is not None and settings_file is not None:raise ValueError('Choose settings or settings_file')
    config=load_settings(chamber,settings_file) if settings is None else validate_settings(settings)
    if config['chamber']!=chamber:raise ValueError('Chamber mismatch')
    roles=load_roles(mapping_file) if mapping_file or 'roles' not in config else dict(schema_version=1,setup='EC',routes={c:dict(PMT='PMTFA' if c=='EA' else 'PMTFC',AOM='AOMA' if c=='EA' else 'AOMC') for c in ('EA','EC')})
    if mapping_file is None and 'roles' in config:roles['routes'][chamber]=validate_route(config['roles'])
    return {'settings':config,'mapping':roles,'hardware_definition':hd.__name__}
