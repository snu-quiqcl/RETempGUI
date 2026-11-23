from labremote.devices.fpga.mapping import settings_path
import json
import math
from copy import deepcopy
from pathlib import Path
from labremote.configuration.paths import CONFIG_ROOT
from labremote.devices.fpga.controller import hd, INPUTS
from labremote.devices.fpga.mapping import PINS, ROLE_KINDS, capability, RouteChoices

ROOT=CONFIG_ROOT/'operations/characterization'
COUNTER_PINS=tuple(pin for pin in PINS if 'counter' in capability(pin))
OUTPUT_PINS=tuple(pin for pin in PINS if 'output' in capability(pin))
FAST_PINS=tuple(pin for pin in PINS if capability(pin)=='fast output')
PMTS=tuple(name for name,kind in ROLE_KINDS.items() if kind=='input')
AOMS=RouteChoices(tuple(name for name,kind in ROLE_KINDS.items() if 'output' in kind), 'output')
PMTS=RouteChoices(PMTS, 'counter')


def read(path):
    from labremote.configuration.experiment_settings import read as read_settings
    return read_settings(path)


def save(path,value):
    from labremote.configuration.experiment_settings import save as save_settings
    save_settings(path,value)


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
    if not isinstance(route,dict) or set(route)-{'PMT','AOM'} or route.get('PMT') not in PMTS:
        raise ValueError('Select a counter input and an output pin')
    return deepcopy(route)


def validate_roles(value):
    if not isinstance(value,dict) or value.get('schema_version')!=1 or value.get('setup')!='EC':raise ValueError('Expected EC setup mapping schema 1')
    if set(value.get('routes',{}))!={'EA','EC'}:raise ValueError('Both EA and EC mappings are required')
    for route in value['routes'].values():
        if not isinstance(route,dict) or set(route)-{'PMT','AOM'} or route.get('PMT') not in PMTS:raise ValueError('Select a counter input and an output pin')
    return deepcopy(value)


def load_settings(chamber,path=None):
    if chamber not in ('EA','EC'):raise ValueError('Select EA or EC')
    local=settings_path(ROOT/f'fluorescence_{chamber}.json')
    value=validate_settings(read(path or (local if local.exists() else ROOT/f'fluorescence_{chamber}.json')))
    if value['chamber']!=chamber:raise ValueError('Settings chamber does not match this tab')
    if 'roles' not in value:
        legacy=settings_path(ROOT/'fpga_roles.json')
        value['roles']=validate_route(read(legacy if legacy.exists() else ROOT/'fpga_roles.json')['routes'][chamber])
    return value


def load_roles(path=None):
    local=settings_path(ROOT/'fpga_roles.json')
    return validate_roles(read(path or (local if local.exists() else ROOT/'fpga_roles.json')))


def sequence_hardware(route, *, include_output=True):
    """Resolve sequence aliases without modifying the shared HardwareDefinition."""
    from types import SimpleNamespace
    if route.get('PMT') not in PMTS or include_output and route.get('AOM') not in AOMS:raise ValueError('Invalid sequence role mapping')
    h = SimpleNamespace(PMT_counter_reset=getattr(hd,route['PMT']+'_counter_reset'),
        PMT_counter_enable=getattr(hd,route['PMT']+'_counter_enable'),
        PMT_counter_result=getattr(hd,route['PMT']+'_counter_result'),
        counter_control_port=hd.counter_control_port,
        external_control_port=hd.external_control_port)
    if include_output:h.AOM_out=getattr(hd,route['AOM']+'_out')
    return h


def prepare(chamber,settings=None,settings_file=None,mapping_file=None):
    if settings is not None and settings_file is not None:raise ValueError('Choose settings or settings_file')
    config=load_settings(chamber,settings_file) if settings is None else validate_settings(settings)
    if config['chamber']!=chamber:raise ValueError('Chamber mismatch')
    if mapping_file or 'roles' not in config:
        path=mapping_file or settings_path(ROOT/'fpga_roles.json')
        roles=read(path)
        roles['routes'][chamber]=validate_route(roles['routes'][chamber])
    else:roles=dict(schema_version=1,setup='EC',routes={chamber:validate_route(config['roles'])})
    return {'settings':config,'mapping':roles,'hardware_definition':hd.__name__}
