"""Read-only Queue result adapters. Never execute a workflow or query hardware."""
import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from .workflow_queue import expand_steps, workflow_jobs,validate_plan


def kinds(job):
    """Inspect source without importing it. Unknown workflows retain a generic panel."""
    found=set()
    try:
        tree=ast.parse(job.get('source',''))
        for node in ast.walk(tree):
            if isinstance(node,ast.Call):
                name=getattr(node.func,'attr',getattr(node.func,'id',''))
                found.update({'run_ion_check':'ion','run_spam':'spam','run_entanglement':'ent'}.get(name, '').split())
    except (ValueError,SyntaxError):pass
    if Path(job.get('filename','')).name=='ion_check_workflow.py':found.add('ion')
    return sorted(found) or ['generic']


def preview(plan):
    if plan.get('jobs'):plan=validate_plan(plan)
    return dict(schema_version=1,queue_id='preview',status='preview',folder='',plan=deepcopy(plan),steps=expand_steps(plan))


def group_key(step):
    # The outer Queue repetition is separate from a group's own accumulating cycles.
    return (step.get('iteration',1),step.get('group_id','job:'+step.get('job_id',step['step_id'])))


def settings_key(settings):
    return hashlib.sha256(json.dumps(settings,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:12]


def pool_spam(analyses):
    """Pool sufficient statistics per target, then equally weight the two targets."""
    states=[]
    for condition in (0,1):
        rows=[s for a in analyses for s in a['states'] if s['condition']==condition]
        totals={k:sum(s[k] for s in rows) for k in ('N_attempts','N_success','N_received','N_error')}
        n=totals['N_received'];error=totals['N_error']/n if n else None
        states.append(dict(condition=condition,**totals,spam_error=error))
    errors=[s['spam_error'] for s in states]
    return dict(states=states,spam_fidelity=1-sum(errors)/2 if all(e is not None for e in errors) else None)


def pool_ent(records):
    from labremote.entanglement.plotting import Accumulator
    if not records:return None,None
    c=records[0]['settings'];acc=Accumulator(c)
    for record in records:
        if record['settings']!=c:raise ValueError('Different entanglement settings cannot be pooled')
        for b in record['batches']:
            acc.add(dict(b,batch=len(acc.batches)))
    return c,acc.data()


class EntPool:
    """Append-only fast path, rebuilding safely on replacement/reordering."""
    def __init__(self):
        self.settings=None;self.batches=[];self.acc=None;self.value=(None,None)

    def update(self,records):
        from labremote.entanglement.plotting import Accumulator
        if not records:
            self.__init__();return self.value
        c=records[0]['settings']
        if any(r['settings']!=c for r in records):raise ValueError('Different entanglement settings cannot be pooled')
        batches=[b for r in records for b in r['batches']]
        prefix=(self.settings==c and len(batches)>=len(self.batches)
                and all(a is b or a==b for a,b in zip(self.batches,batches)))
        if prefix and len(batches)==len(self.batches):return self.value
        if not prefix:self.acc=Accumulator(c);self.batches=[];self.settings=c
        for b in batches[len(self.batches):]:self.acc.add(dict(b,batch=len(self.acc.batches)))
        self.batches=batches;self.value=(c,self.acc.data())
        return self.value


class ResultStore:
    """One reader thread; index directory entries, validate file revisions each poll."""
    def __init__(self):
        self.cache={};self.directories={};self.record_cache={};self.pools={};self.revision=0

    def discover(self,folder):
        folder=Path(folder)
        if folder.is_file():return [folder.resolve()]
        found=[];pending=[folder]
        while pending:
            current=pending.pop()
            try:stamp=current.stat().st_mtime_ns
            except FileNotFoundError:continue
            old=self.directories.get(current)
            if old is None or old[0]!=stamp:
                children=[];files=[]
                with os.scandir(current) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):children.append(Path(entry.path))
                        elif entry.name in ('result.json','results.json','samples.json'):
                            files.append(Path(entry.path).resolve())
                old=(stamp,children,files);self.directories[current]=old
            pending.extend(old[1]);found.extend(old[2])
        return found

    @staticmethod
    def stamp(path):
        try:
            stat=path.stat();return stat.st_mtime_ns,stat.st_size
        except FileNotFoundError:return None

    def records(self,state,step,warnings):
        if not state.get('folder') or not step.get('directory'):return []
        root=Path(state['folder']);directory=root/step['directory']
        roots=[directory]
        for name in step.get('result',{}).get('result_paths',[]):
            path=Path(name);roots.append(path if path.is_absolute() else root/path)
        files=set(p for folder in dict.fromkeys(roots) for p in self.discover(folder))
        dependencies=set(files)
        for path in files:dependencies.update((path.parent/'configuration.json',path.parent/'analysis.json'))
        if step.get('result_file'):dependencies.add(root/step['result_file'])
        signature=(tuple((str(p),self.stamp(p)) for p in sorted(dependencies)),
                   settings_key(step['result']['value']) if step.get('result',{}).get('value') is not None else None)
        key=(str(directory),step['step_id'])
        old=self.record_cache.get(key)
        if old is not None and old[0]==signature:return old[1]
        errors=[]
        result=self._records(state,step,errors,files)
        self.revision+=1
        for record in result:
            record['_revision']=self.revision
            if record['kind']=='ent':
                record['_summary']=f"{sum(b['heralded'] for b in record['batches'])} herald / {sum(b['attempts'] for b in record['batches']):,} trials"
        if not errors:self.record_cache[key]=(signature,result)
        else:self.record_cache.pop(key,None)
        warnings.extend(errors)
        return result

    def read(self,path):
        path=Path(path);stat=path.stat();stamp=(stat.st_mtime_ns,stat.st_size)
        key=str(path.resolve());old=self.cache.get(key)
        if old and old[0]==stamp:return old[1]
        from .json_storage import read_json
        value=read_json(path)
        self.cache[key]=(stamp,value)
        return value

    def _records(self,state,step,warnings,discovered):
        root=Path(state['folder']);directory=root/step['directory']
        files={p for p in discovered if p.name!='samples.json'}
        output=[];seen=set()
        for path in sorted(files):
            try:
                d=self.read(path);kind=d.get('experiment');base=path.parent
                identity=(kind,d.get('run_id') or d.get('folder') or str(base))
                if identity in seen:continue
                previous=len(output)
                if kind=='entanglement':
                    from labremote.entanglement.config import validate
                    c=validate(d['configuration']['settings'])
                    batches=[b['measurement'] for b in d['batches'] if b['status']=='completed']
                    # Failed/aborted FPGA batches are excluded, including during live reads.
                    output.append(dict(kind='ent',settings=c,batches=batches,status=d['status'],path=str(path),
                                       excluded=sum(b['status']!='completed' for b in d['batches'])))
                elif kind=='spam':
                    c=self.read(base/'configuration.json')['settings'];a=self.read(base/'analysis.json')
                    output.append(dict(kind='spam',settings=c,analysis=a,chamber=d['chamber'],status=d['status'],path=str(path)))
                elif 'samples' in d and 'dac' in d:
                    output.append(dict(kind='ion',settings=d['settings'],samples=d['samples'],status=d['status'],path=str(path)))
                if len(output)>previous:seen.add(identity)
            except Exception as exc:warnings.append(f'{step["step_id"]} · {path.name}: {exc}')
        # Ion Check checkpoints exist before its final result; replace, never append to it.
        if not any(r['kind']=='ion' for r in output):
            for path in sorted(p for p in discovered if p.name=='samples.json' and directory in p.parents):
                try:
                    cfg=self.read(path.parent/'configuration.json')
                    if cfg.get('dac') in ('not_connected','not_implemented'):
                        output.append(dict(kind='ion',settings=cfg['settings'],samples=self.read(path),status='running',path=str(path.parent/'result.json')))
                except Exception as exc:warnings.append(f'{step["step_id"]}: {exc}')
        # Legacy frozen Ion Check workflow stores history in the workflow return value.
        if not any(r['kind']=='ion' for r in output) and step.get('result_file'):
            try:
                d=self.read(root/step['result_file']);value=d.get('value')
                if isinstance(value,dict) and isinstance(value.get('history'),list):
                    c={'threshold_'+k:v for k,v in value.get('thresholds',{}).items()}
                    output.append(dict(kind='ion',settings=c,samples=value['history'],status=d['status'],path=str(root/step['result_file'])))
            except Exception as exc:warnings.append(f'{step["step_id"]}: {exc}')
        if not any(r['kind']=='ion' for r in output):
            value=step.get('result',{}).get('value')
            if isinstance(value,dict) and isinstance(value.get('history'),list):
                c={'threshold_'+k:v for k,v in value.get('thresholds',{}).items()}
                output.append(dict(kind='ion',settings=c,samples=value['history'],status=step['status'],path=str(directory/'result.json')))
        return output

    def snapshot(self,state):
        from .queue_archive import hydrate
        state=hydrate(state)
        jobs={j['id']:j for j in workflow_jobs(state.get('plan',{}).get('jobs',[]))}
        from .monitor_config import settings
        monitors={jid:settings(job) for jid,job in jobs.items()}
        job_kinds={jid:([m['kind']] if m['kind']!='none' else []) for jid,m in monitors.items()}
        groups={};warnings=[]
        for step in state['steps']:
            key=group_key(step)
            group=groups.setdefault(key,dict(key=key,name=step.get('group_name',step['name']),iteration=key[0],steps=[],slots={}))
            group['steps'].append(step)
            job=jobs.get(step.get('job_id'),dict(name=step['name'],id=step.get('job_id',step['step_id'])))
            jid=job['id'];expected=job_kinds.get(jid,[])
            monitor=monitors.get(jid,{})
            if not expected:continue
            for kind in expected:
                group['slots'].setdefault((jid,kind,''),dict(job_id=jid,name=monitor.get('title') or job['name'],monitor=monitor,kind=kind,profile='',records=[]))
            if step['status'] in ('pending','skipped'):continue
            records=self.records(state,step,warnings)
            if not any(r['kind'] in expected for r in records) and step['status']=='completed':
                warnings.append(f'{step["step_id"]} · 완료된 workflow의 측정 결과 파일을 찾지 못했습니다.')
            for record in records:
                kind=record['kind']
                if kind not in expected:
                    warnings.append(f'{step["step_id"]} · Monitor 종류와 결과 종류가 다릅니다: {expected[0]} / {kind}')
                    continue
                profile=settings_key(record['settings'])
                slot=group['slots'].setdefault((jid,kind,profile),dict(job_id=jid,name=monitor.get('title') or job['name'],monitor=monitor,kind=kind,profile=profile,records=[]))
                record=dict(record,step_id=step['step_id'],cycle=step.get('group_iteration',step['job_repeat']),
                            job_repeat=step['job_repeat'],step_status=step['status'])
                slot['records'].append(record)
        active_pools=set()
        for group in groups.values():
            slots=group['slots']
            for key in list(slots):
                jid,kind,profile=key
                if not profile and any(k[0]==jid and k[1]==kind and k[2] for k in slots):del slots[key]
                elif kind=='generic' and any(k[0]==jid and k[1]!='generic' for k in slots):del slots[key]
            # SPAM EA/EC have distinct settings; keep them in one workflow panel,
            # but retain profile identity for independent weighted statistics.
            spam={}
            for key,slot in list(slots.items()):
                if slot['kind']=='spam':
                    dest=spam.setdefault(slot['job_id'],dict(slot,profile='',records=[]))
                    dest['records'].extend(slot['records']);del slots[key]
            for jid,slot in spam.items():slots[jid,'spam','']=slot
            order={jid:i for i,jid in enumerate(jobs)}
            group['slots']=sorted(slots.values(),key=lambda s:order.get(s['job_id'],len(order)))
            for slot in group['slots']:
                slot['variant']=sum(s['job_id']==slot['job_id'] and s['kind']==slot['kind'] for s in group['slots'])>1
                # Small GUI revision token; never serialize all photon histograms there.
                slot['_signature']=(slot['name'],slot['variant'],json.dumps(slot['monitor'],sort_keys=True),
                    tuple((r['path'],r['_revision'],r['cycle'],r['step_id'],r['step_status']) for r in slot['records']))
                if slot['kind']=='ent':
                    cycles={}
                    for record in slot['records']:cycles.setdefault(record['cycle'],[]).append(record)
                    views={}
                    for cycle,records in [(None,slot['records']),*cycles.items()]:
                        key=(group['key'],slot['job_id'],slot['profile'],cycle);active_pools.add(key)
                        views[cycle]=self.pools.setdefault(key,EntPool()).update(records)
                    slot['_ent_views']=views
        self.pools={k:v for k,v in self.pools.items() if k in active_pools}
        return dict(state=state,groups=list(groups.values()),warnings=warnings)
