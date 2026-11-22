"""Run with the OLD checkout before pull; export that PC's own Python defaults.

Copy this script outside the repository, close the GUI and back up first.
Usage: python -B export_local_defaults.py --repo D:/path/to/RETempGUI
No existing config is overwritten. No devices are connected.
"""
import argparse
import importlib
import json
import sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args();root=args.repo.resolve()
    if not (root/'labremote').is_dir():parser.error('Expected the RETempGUI repository root')
    sys.path.insert(0,str(root))
    cases=[('micromotion.config',[(c,) for c in ('EA','EC')],lambda c:'micromotion_'+c),
           ('micromotion.secular.config',[(c,) for c in ('EA','EC')],lambda c:'secular_'+c),
           ('characterization.rabi',[(c,) for c in ('EA','EC')],lambda c:'rabi_'+c),
           ('characterization.pulse_experiment',[(k,c) for k in ('initialization','ramsey','spin_echo','spam') for c in ('EA','EC')],lambda k,c:k+'_'+c),
           ('decay.config',[(c,m) for c in ('EA','EC') for m in ('171_single','174_single','171_dual','174_dual')],lambda c,m:'decay_'+c+'_'+m),
           ('hom.config',[()],lambda:'hom'),('entanglement.config',[()],lambda:'entanglement'),('ion_check.config',[()],lambda:'ion_check')]
    profiles={}
    # Collect everything first: an import failure must not leave a partial export.
    for module,calls,name in cases:
        source=importlib.import_module('labremote.'+module)
        for call in calls:profiles[name(*call)]=source.defaults(*call)
    for module,name in [('phase_shifter.config','phase_ramsey'),('phase_shifter.rabi','phase_rabi')]:
        profiles[name]=importlib.import_module('labremote.'+module).DEFAULTS
    oven=importlib.import_module('labremote.devices.oven.settings')
    profiles['oven']=dict(oven.DEFAULTS,profiles=oven.PROFILES)
    power=importlib.import_module('labremote.operation.oven_psu.control')
    timing=importlib.import_module('labremote.operation.dac.timing')
    profiles['dac_timing']=dict(timing.ManualTiming().as_dict(),sequence_pre_ldac_ms=timing.SequenceOptions().pre_ldac_ms)
    if hasattr(power,'_POLICY'):profiles['oven_power']=power._POLICY
    else:
        # Older code kept tolerance/poll values as literals inside off().
        import ast,inspect,textwrap
        tree=ast.parse(textwrap.dedent(inspect.getsource(power.off)))
        tolerances=[n.comparators[0].value for n in ast.walk(tree) if isinstance(n,ast.Compare) and isinstance(n.left,ast.Call) and isinstance(n.left.func,ast.Name) and n.left.func.id=='abs' and isinstance(n.comparators[0],ast.Constant)]
        polls=[n.args[0].value for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='wait' and n.args and isinstance(n.args[0],ast.Constant)]
        if len(tolerances)!=1 or len(polls)!=1:raise ValueError('Cannot identify this PC oven tolerance/poll; export manually before pull')
        profiles['oven_power']=dict(off_current_timeout_s=power.OFF_CURRENT_TIMEOUT_S,ramp_step_a=power.RAMP_STEP_A,ramp_interval_s=power.RAMP_INTERVAL_S,off_current_tolerance_a=tolerances[0],off_poll_s=polls[0])
    folder=root/'labremote/config/operations/defaults';folder.mkdir(parents=True,exist_ok=True)
    profiles['oven']['power']=profiles['oven_power']
    created=[];retained=[]
    payloads={name:json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n' for name,value in profiles.items()}
    for name,payload in payloads.items():
        path=(root/'labremote/config/operations/oven.json') if name=='oven' else folder/(name+'.json')
        if name=='oven_power':continue
        try:
            with path.open('x',encoding='utf8') as stream:stream.write(payload)
            created.append(name)
        except FileExistsError:retained.append(name)
    print(json.dumps(dict(created=created,retained=retained),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
