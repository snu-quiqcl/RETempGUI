"""Simulate two old checkouts -> updated source; no commits/pull or real config edits."""
import hashlib,io,json,os,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def hashes(folder):return {str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}
files=git('ls-files','--cached','--others','--exclude-standard').decode('utf8').splitlines()
archive=git('archive','--format=zip','HEAD')
results=[]
with tempfile.TemporaryDirectory(prefix='retemp-update-check-') as temporary:
    for pc,voltage,step,timeout in [('EA',.16,.173,43.),('EC',.19,.217,57.)]:
        checkout=Path(temporary)/pc;checkout.mkdir()
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:bundle.extractall(checkout)
        config=checkout/'labremote/config'
        shutil.copytree(ROOT/'labremote/config',config,ignore=lambda path,names:{'defaults'} if Path(path)==ROOT/'labremote/config/operations' else {'__pycache__'})
        # Distinct local file and legacy Python-only defaults on each PC.
        (config/'pc_marker.json').write_text(json.dumps(dict(pc=pc,voltage=voltage)))
        power=checkout/'labremote/operation/oven_psu/control.py'
        old=power.read_text(encoding='utf8')
        if 'RAMP_STEP_A = .15' not in old:raise AssertionError('Run this check against the pre-migration HEAD')
        power.write_text(old.replace('RAMP_STEP_A = .15',f'RAMP_STEP_A = {step}'),encoding='utf8')
        rabi=checkout/'labremote/characterization/rabi.py'
        rabi.write_text(rabi.read_text(encoding='utf8').replace('timeout_s=30.',f'timeout_s={timeout}'),encoding='utf8')
        subprocess.run([sys.executable,'-B',str(ROOT/'tools/export_local_defaults.py'),'--repo',str(checkout)],cwd=checkout,check=True,stdout=subprocess.PIPE)
        before=hashes(config)
        for name in files:
            source=ROOT/name
            if source.is_file():
                destination=checkout/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
        assert hashes(config)==before,'Source update changed local config'
        code="from labremote.characterization.rabi import defaults;from labremote.operation.oven_psu.control import RAMP_STEP_A;import json;print(json.dumps([defaults('EA')['timeout_s'],RAMP_STEP_A]))"
        actual=json.loads(subprocess.check_output([sys.executable,'-B','-c',code],cwd=checkout,text=True))
        assert actual==[timeout,step],actual
        subprocess.run([sys.executable,'-B',str(checkout/'tools/export_local_defaults.py'),'--repo',str(checkout)],cwd=checkout,check=True,stdout=subprocess.PIPE)
        assert hashes(config)==before,'Second export overwrote existing settings'
        results.append(dict(pc=pc,local_files=len(before),timeout_s=actual[0],ramp_step_a=actual[1],config_hashes_unchanged=True))
print(json.dumps(results,indent=2));print('PASS: both PCs preserve local config and custom Python defaults across source update')
