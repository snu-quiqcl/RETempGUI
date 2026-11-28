"""Built-in RE entry points; local/frozen workflows remain valid."""
from pathlib import Path
from importlib import import_module

ROOT = Path(__file__).resolve().parents[1]
SPECS = {
    'entanglement': dict(name='re_with_flip_mirror', title='RE with flip mirror',
                        monitor='ent_with_mirror', method='run_entanglement'),
    'entanglement_no_mirror': dict(name='re_without_flip_mirror', title='RE without flip mirror',
                                  monitor='ent_without_mirror', method='run_entanglement_no_mirror'),
}

def path(experiment):
    return ROOT / 'experiments' / experiment / 'workflow.py'

def entries():
    return [(v['name'], path(k)) for k,v in SPECS.items()]

def model(experiment):
    return import_module('labremote.experiments.'+experiment+'.config')

def experiment(job):
    from .workflow_ui import editor_kind
    try:kind=editor_kind(job.get('source',''))
    except (SyntaxError,ValueError):return None
    if kind in SPECS:return kind
    p=job.get('parameters',{})
    kind={'EntanglementTab':'entanglement','EntanglementNoMirrorTab':'entanglement_no_mirror'}.get(p.get('kind'))
    if kind:return kind
    name=Path(job.get('filename','')).name
    if name in ('re.py','queue_entanglement.py','re_with_flip_mirror.py'):return 'entanglement'
    if name=='re_without_flip_mirror.py':return 'entanglement_no_mirror'
    return None

def saved_parameters(experiment, profile):
    """Read exactly the selected FPGA's standalone settings and role mappings."""
    from labremote.devices.fpga.mapping import scope, editing_settings
    from labremote.devices.fpga.routing import normalize
    with scope(profile,experiment), editing_settings():
        c=model(experiment).load()
        c=normalize(c,experiment,None,profile)
    return dict(fpga=profile.device_id,settings=c)
