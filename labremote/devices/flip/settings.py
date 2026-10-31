import json
import os
from pathlib import Path

LOCAL=Path(__file__).resolve().parents[2]/'config'/'flip.local.json'


def validate_settings(data):
    if not isinstance(data['host'],str) or type(data['port']) is not int or not 1<=data['port']<=65535:
        raise ValueError('Invalid flipper endpoint in flip.local.json')
    if type(data['auto_route']) is not bool:raise ValueError('auto_route must be true or false')
    names=data.get('names',[])
    if not isinstance(names,list) or any(not isinstance(n,str) or not n.isidentifier() for n in names) or len(set(names))!=len(names):
        raise ValueError('Flipper names must be unique server instrument identifiers')
    if not isinstance(data['routes'],dict) or set(data['routes'])-{'EA','EC'}:raise ValueError('Routes must be EA / EC')
    for chamber,route in data['routes'].items():
        if not isinstance(route,dict) or any(not isinstance(n,str) or not n.isidentifier() for n in route):
            raise ValueError('Invalid server flipper name in '+chamber)
        if any(type(v) is not int or v not in (1,2) for v in route.values()):raise ValueError('Route positions must be 1 or 2')
    return data


def load_settings():
    data={'host':'','port':5556,'names':[],'auto_route':False,'routes':{'EA':{},'EC':{}}}
    if LOCAL.exists():data.update(json.loads(LOCAL.read_text(encoding='utf-8-sig')))
    return validate_settings(data)


def save_settings(data):
    validate_settings(data)
    temp=LOCAL.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8');os.replace(temp,LOCAL)


def save_endpoint(host,port):
    data=load_settings()
    # A route belongs to a server endpoint; never apply it to a different server.
    if (data['host'],data['port'])!=(host,port):
        data.update(names=[],auto_route=False,routes={'EA':{},'EC':{}})
    data.update(host=host,port=port);save_settings(data)
    return data
