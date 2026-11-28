"""Versioned Queue archives. Runtime context never changes instrument commands."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import threading
from .monitor_config import is_ent

LAYOUT='group_common_v2'
CURRENT=ContextVar('queue_archive',default=None)

def active():return CURRENT.get() is not None

@contextmanager
def scope(directory):
    token=CURRENT.set({'directory':Path(directory),'used':set(),'lock':threading.Lock()})
    try:yield
    finally:CURRENT.reset(token)

def allocate(candidate):
    context=CURRENT.get()
    if context is None:return None
    parent=Path(candidate).parent
    # Honor intentional workflow subdirectories (e.g. EA/EC or scan points).
    with context['lock']:
        result=parent;n=2
        while result in context['used'] or (result.exists() and any(result.iterdir())):
            result=parent/f'run_{n:02d}';n+=1
        context['used'].add(result)
    return result

def group_directory(root,directory):
    parts=Path(directory).parts
    return Path(root).joinpath(*parts[:2])

def archive_manifest(state):
    """Write immutable common definitions only when their contents change."""
    from .workflow_queue import save,is_group
    root=Path(state['folder']);plan=state['plan'];profiles={};references=[]
    steps={s['job_id']:s for s in state['steps']}
    groups=[];ungrouped=[]
    for item in plan['jobs']:
        if is_group(item):groups.append((item,item['jobs']))
        else:ungrouped.append(item)
    if ungrouped:groups.append((None,ungrouped))
    for group,jobs in groups:
        if not jobs:continue
        step=steps[jobs[0]['id']]
        common=group_directory(root,step['planned_directory'])/'group_config.json'
        definition=deepcopy(group) if group else {'jobs':deepcopy(jobs)}
        for job in definition['jobs']:
            refs={}
            for name,profile in job.pop('fpga_profiles',{}).items():
                key=hashlib.sha256(json.dumps(profile,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                profiles[key]=profile;refs[name]=key
            job['fpga_profile_refs']=refs
        document={'schema_version':1,'group':definition,'ungrouped':group is None}
        write_changed(common,document)
        references.append(str(common.relative_to(root)))
    write_changed(root/'fpga_profiles.json',{'schema_version':1,'profiles':profiles})
    disk=deepcopy(state);disk.pop('plan',None)
    disk['plan_metadata']={k:v for k,v in plan.items() if k!='jobs'}
    disk['job_order']=[j['id'] for j in plan['jobs']]
    disk['group_configs']=references
    return disk

def write_changed(path,value):
    from .workflow_queue import save
    if path.exists():
        try:
            if json.loads(path.read_text(encoding='utf-8'))==value:return
        except (OSError,ValueError):pass
    save(path,value)

def hydrate(state,root=None):
    if state.get('storage_layout')!=LAYOUT or 'plan' in state:return state
    root=Path(root or state['folder']);state=deepcopy(state);items={}
    profiles=json.loads((root/'fpga_profiles.json').read_text(encoding='utf-8'))['profiles']
    for name in state['group_configs']:
        path=(root/name).resolve()
        if not path.is_relative_to(root.resolve()):raise ValueError('Invalid group config path')
        doc=json.loads(path.read_text(encoding='utf-8'));group=doc['group']
        for job in group['jobs']:
            job['fpga_profiles']={name:deepcopy(profiles[key]) for name,key in job.pop('fpga_profile_refs',{}).items()}
        if doc['ungrouped']:items.update((j['id'],j) for j in group['jobs'])
        else:items[group['id']]=group
    from labremote.configuration.experiment_settings import plan as decode_plan
    state['plan']=decode_plan(dict(state['plan_metadata'],jobs=[items[key] for key in state['job_order']]),encode=False)
    state['folder']=str(root)
    return state

def finalize_ready(state,force=False):
    """Export once after a group terminates, never at each measurement boundary."""
    from .queue_monitor_data import ResultStore,group_key
    groups={}
    for step in state['steps']:groups.setdefault(group_key(step),[]).append(step)
    exports=state.setdefault('group_exports',{})
    for key,steps in groups.items():
        identity=json.dumps(key)
        if identity in exports:continue
        if not force and any(s['status'] in ('pending','running') for s in steps):continue
        if not any('directory' in s for s in steps):continue
        partial=any(s['status']!='completed' for s in steps)
        subset=dict(state,steps=steps)
        # Export saved measurements even if the user disabled the live monitor.
        store=ResultStore();slots={};warnings=[]
        from .workflow_queue import workflow_jobs
        jobs={j['id']:j for j in workflow_jobs(state['plan']['jobs'])}
        for step in steps:
            for record in store.records(state,step,warnings):
                if record['kind']=='spam' and 'run_spam_scan' in jobs.get(step['job_id'],{}).get('source',''):continue
                from .queue_monitor_data import settings_key
                profile='' if record['kind']=='spam' else settings_key(dict(settings=record['settings'],fpga=record.get('fpga'))) if is_ent(record['kind']) else settings_key(record['settings'])
                slot=slots.setdefault((step['job_id'],record['kind'],profile),dict(job_id=step['job_id'],kind=record['kind'],profile=profile,records=[]))
                slot['records'].append(dict(record,cycle=step.get('group_iteration',step['job_repeat'])))
        for slot in slots.values():slot['variant']=sum(s['job_id']==slot['job_id'] and s['kind']==slot['kind'] for s in slots.values())>1
        paths=export_group(dict(state=subset,groups=[dict(steps=steps,slots=list(slots.values()))]),partial)
        from .queue_extra_plots import export
        paths.extend(export(Path(state['folder']),steps,partial))
        exports[identity]={'status':'partial' if partial else 'completed','images':paths}
        if warnings:exports[identity]['warnings']=warnings

def export_group(snapshot,partial):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from .queue_monitor_data import pool_ent,settings_key
    root=Path(snapshot['state']['folder']);paths=[]
    prefix='partial' if partial else 'final'
    for group in snapshot['groups']:
        for slot in group['slots']:
            records=slot['records']
            if not records:continue
            step=next(s for s in group['steps'] if s['job_id']==slot['job_id'] and 'directory' in s)
            # planned directory ends in the cycle, optionally run_N.
            directory=root/step['directory']
            if directory.name.startswith('run_'):directory=directory.parent
            directory=directory.parent
            if is_ent(slot['kind']):
                from labremote.experiments.entanglement.plotting import EntanglementPlot
                c,data=pool_ent(records)
                if not data['batches']:continue
                figure=Figure(figsize=(14,15));FigureCanvasAgg(figure);EntanglementPlot(figure,c).update(data)
                name=prefix+('_'+slot['profile'] if slot['variant'] else '')+'.png'
                save_figure(figure,directory/name,partial);paths.append(str((directory/name).relative_to(root)))
            elif slot['kind']=='spam':
                from labremote.experiments.characterization.shared.pulse_model import analyze, draw
                profiles={}
                for record in records:
                    if record['status']=='completed':profiles.setdefault((record['chamber'],settings_key(record['settings'])),[]).append(record)
                for (chamber,profile),rows in profiles.items():
                    points=[]
                    for record in rows:
                        points.extend(json.loads((Path(record['path']).parent/'points.json').read_text(encoding='utf-8')))
                    figure=Figure(figsize=(9,10));FigureCanvasAgg(figure)
                    draw(figure,analyze('spam',points,rows[0]['settings']))
                    variant=sum(ch==chamber for ch,p in profiles)>1
                    name=prefix+'_'+chamber+('_'+profile if variant else '')+'.png'
                    save_figure(figure,directory/name,partial);paths.append(str((directory/name).relative_to(root)))
            elif slot['kind']=='ion':
                figure=Figure(figsize=(9,5));FigureCanvasAgg(figure);ax=figure.subplots()
                for channel in 'abc':
                    ax.plot([r['cycle'] for r in records if r['samples']],
                            [r['samples'][-1]['counts'][channel] for r in records if r['samples']],'.-',label=channel.upper())
                ax.set(xlabel='Group cycle',ylabel='Final check counts');ax.legend();ax.grid(alpha=.2)
                name=prefix+('_'+slot['profile'] if slot['variant'] else '')+'.png'
                save_figure(figure,directory/name,partial);paths.append(str((directory/name).relative_to(root)))
    return paths

def save_figure(figure,path,partial):
    import os
    path.parent.mkdir(parents=True,exist_ok=True)
    if partial:figure.suptitle('PARTIAL — completed measurements only')
    temporary=path.with_suffix('.png.tmp')
    figure.savefig(temporary,format='png',dpi=130);os.replace(temporary,path)
