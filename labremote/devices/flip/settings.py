import json
import os
from pathlib import Path

LOCAL=Path(__file__).resolve().parents[2]/'config'/'flip.local.json'
NAMES=tuple(f'flip_{i}' for i in range(1,6))


def load_settings():
    data={'host':'','port':5556,'auto_route':False,'routes':{'EA':{},'EC':{}}}
    if LOCAL.exists():data.update(json.loads(LOCAL.read_text(encoding='utf-8-sig')))
    if not isinstance(data['host'],str) or type(data['port']) is not int or not 1<=data['port']<=65535:
        raise ValueError('Invalid flipper endpoint in flip.local.json')
    if type(data['auto_route']) is not bool:raise ValueError('auto_route must be true or false')
    if not isinstance(data['routes'],dict) or set(data['routes'])-{'EA','EC'}:raise ValueError('Routes must be EA / EC')
    for chamber,route in data['routes'].items():
        if not isinstance(route,dict) or set(route)-set(NAMES):raise ValueError('Unknown flipper in '+chamber)
        if any(type(v) is not int or v not in (1,2) for v in route.values()):raise ValueError('Route positions must be 1 or 2')
    return data


def save_endpoint(host,port):
    data=load_settings();data.update(host=host,port=port)
    temp=LOCAL.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8');os.replace(temp,LOCAL)
