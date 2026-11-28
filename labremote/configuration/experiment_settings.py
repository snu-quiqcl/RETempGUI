"""One persisted FPGA mapping block; legacy sequence shapes stay internal."""
from copy import deepcopy
from pathlib import Path
from labremote.devices.fpga import routing
from labremote.devices.fpga.mapping import CURRENT,Profile,scope

def infer(c,hint=None):
    if not isinstance(c,dict):return None
    if 'spam' in c and isinstance(c['spam'],dict):return 'spam_2d'
    if 'phase_outputs' in c:return 'phase_shifter'
    if 'mapping' in c and 'exposure_us' in c:return 'ion_check'
    if 'basis' in c and 'groups_per_loop' in c:return 'entanglement_no_mirror' if c.get('experiment')=='entanglement_no_mirror' else 'entanglement'
    if 'aomb_enabled' in c and 'inputs' in c:return 'hom'
    if 'mode' in c and 'roles' in c and str(c['mode']).startswith(('171','174')):return 'decay'
    if 'trg_pin' in c or 'counter_pin' in c:return 'secular' if 'start_khz' in c else 'micromotion'
    if 'pmt' in c and ('scan' in c or 'x_start_um' in c):return 'scan'
    if 'roles' in c and ('chamber' in c or c.get('experiment')=='spam'):
        if 'exposure_ms' in c:return 'fluorescence'
        return c.get('experiment') or hint or 'rabi'
    if 'fpga_mapping' in c and c['fpga_mapping'].get('schema_version')==1:return c['fpga_mapping']['experiment']
    return None

def pack(c,hint=None):
    if not isinstance(c,dict):return deepcopy(c)
    exp=infer(c,hint)
    if exp=='spam_2d':
        result=deepcopy(c);result['spam']=pack(c['spam'],'spam');return result
    if not exp:return deepcopy(c)
    if c.get('fpga_mapping',{}).get('schema_version')==1:return deepcopy(c)
    c=routing.normalize(c,exp)
    specs=routing.routes(exp,c,all_fields=True);signals={}
    for spec in specs:
        value=routing.get(c,spec.path)
        if isinstance(value,str) and value.startswith('signal:'):value=value[7:]
        signals[spec.role]=value
    for key in {spec.path[0] for spec in specs}:c.pop(key,None)
    c['fpga_mapping']=dict(schema_version=1,experiment=exp,signals=signals)
    return c

def unpack(c):
    if not isinstance(c,dict):return deepcopy(c)
    if 'spam' in c and isinstance(c['spam'],dict):
        c=deepcopy(c);c['spam']=unpack(c['spam']);return c
    block=c.get('fpga_mapping')
    if not isinstance(block,dict) or block.get('schema_version')!=1:return deepcopy(c)
    if set(block)-{'ui_state_imported'}!={'schema_version','experiment','signals'} or not isinstance(block['signals'],dict):
        raise ValueError('Invalid fpga_mapping settings block')
    c=deepcopy(c);c.pop('fpga_mapping');exp=block['experiment'];signals=block['signals']
    if exp=='phase_shifter' and 'microwave' in signals:c['outputs']={}
    for spec in routing.routes(exp,c,all_fields=True):
        value=signals.get(spec.role)
        if value and exp not in ('phase_shifter','scan'):value='signal:'+value
        routing.put(c,spec.path,value)
    return c

def read(path):
    from labremote.runtime.json_storage import read_json
    value=read_json(path)
    if isinstance(value,dict) and value.get('document_type')=='entanglement_settings':
        value['settings']=unpack(value['settings']);return value
    return unpack(value)


def mapping_block(value):
    """Find the mapping owner in normal, SPAM scan and preset documents."""
    if not isinstance(value,dict):return None
    if value.get('document_type')=='entanglement_settings':return mapping_block(value.get('settings'))
    if isinstance(value.get('spam'),dict):return mapping_block(value['spam'])
    block=value.get('fpga_mapping')
    return block if isinstance(block,dict) and block.get('schema_version')==1 else None


def save(path,value,experiment=None,*,ui_state_imported=True):
    from labremote.runtime.json_storage import save_json
    state=CURRENT.get();hint=experiment or (state[1] if state else None)
    if isinstance(value,dict) and value.get('document_type')=='entanglement_settings':
        value=deepcopy(value);value['settings']=pack(value['settings'],'entanglement')
    else:value=pack(value,hint)
    block=mapping_block(value)
    if block is not None:block['ui_state_imported']=ui_state_imported
    import json
    path=Path(path)
    if path.exists():
        try:
            if json.loads(path.read_text(encoding='utf-8-sig'))==value:return
        except (ValueError,OSError):pass
    save_json(path,value)

def plan(value,*,encode):
    """Queue stores a self-contained settings copy using its frozen board names."""
    if isinstance(value,list):return [plan(v,encode=encode) for v in value]
    if not isinstance(value,dict):return deepcopy(value)
    result={k:plan(v,encode=encode) for k,v in value.items() if k not in ('parameters','fpga_profiles')}
    if 'fpga_profiles' in value:result['fpga_profiles']=deepcopy(value['fpga_profiles'])
    if 'parameters' in value:
        params=deepcopy(value['parameters']);profile_doc=value.get('fpga_profiles',{}).get(params.get('fpga'))
        def convert(c):
            if isinstance(c,dict) and set(c)=={'EA','EC'}:return {ch:convert(v) for ch,v in c.items()}
            return pack(c,params.get('experiment_kind')) if encode else unpack(c)
        if 'settings' in params:
            if profile_doc:
                with scope(Profile(profile_doc)):params['settings']=convert(params['settings'])
            else:params['settings']=convert(params['settings'])
        if 'mapping_experiments' in params:
            for entry in params['mapping_experiments']:
                if isinstance(entry,dict) and isinstance(entry.get('settings'),dict):
                    if profile_doc:
                        with scope(Profile(profile_doc)):
                            entry['settings']=pack(entry['settings'],entry.get('experiment')) if encode else unpack(entry['settings'])
                    else:entry['settings']=pack(entry['settings'],entry.get('experiment')) if encode else unpack(entry['settings'])
        result['parameters']=params
    return result
