"""Sequential workflow queue. Each step owns an independent cancellation group."""
import hashlib
import json
import math
import os
import threading
import time
import traceback
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from labremote.data_paths import tab_data_directory
from uuid import uuid4
from .jobs import CancellationToken
from .errors import OperationCancelled
from .workflow_loader import validate_workflow,load_workflow
from .workflow_runner import run_workflow
from .workflow_result import WorkflowResult,workflow_session

def now():return datetime.now(timezone.utc).isoformat()

def serializable(value):
    if value is None or isinstance(value,(str,bool,int)):return value
    if isinstance(value,float):return value if math.isfinite(value) else None
    if isinstance(value,dict):return {str(k):serializable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [serializable(v) for v in value]
    if isinstance(value,Path):return str(value)
    if hasattr(value,'tolist'):return serializable(value.tolist())
    return repr(value)

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.tmp')
    with temp.open('w',encoding='utf-8') as f:
        json.dump(serializable(value),f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(temp,path)

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def freeze_job(filename,*,name=None,repeat=1,on_failure='stop',parameters=None,monitor=None):
    path=Path(filename).resolve();source=path.read_text(encoding='utf-8-sig');validate_workflow(source,str(path))
    job = dict(id=uuid4().hex,name=name or path.stem,filename=str(path),source=source,sha256=hashlib.sha256(source.encode()).hexdigest(),repeat=repeat,on_failure=on_failure,parameters=deepcopy(parameters or {}))
    from .monitor_config import suggested,validate
    job['monitor']=deepcopy(validate(monitor) if monitor is not None else suggested(job))
    from labremote.devices.fpga.mapping import CURRENT
    state = CURRENT.get()
    if state is not None:
        job['fpga_profiles'] = {state[0].device_id: state[0].document()}
        job['fpga_id'] = state[0].device_id
    return job

def is_group(job):
    return isinstance(job,dict) and job.get('type')=='repeat_group'


def make_group(jobs, *, name='Repeat Group', repeat=1, on_failure='stop'):
    return dict(type='repeat_group',id=uuid4().hex,name=name,repeat=repeat,
                on_failure=on_failure,jobs=deepcopy(jobs))


def workflow_jobs(items):
    for item in items:
        yield from item['jobs'] if is_group(item) else [item]


def validate_plan(plan):
    if not isinstance(plan,dict) or type(plan.get('schema_version')) is not int or plan['schema_version'] not in (1,2):raise ValueError('Queue schema_version must be 1 or 2')
    if type(plan.get('repeat')) is not int or not 1<=plan['repeat']<=10000:raise ValueError('Queue repeat must be 1..10000')
    jobs=plan.get('jobs')
    if not isinstance(jobs,list) or not jobs or len(jobs)>10000:raise ValueError('Add at least one workflow (maximum 10000)')
    ids=set()
    total=0
    for item in jobs:
        if is_group(item):
            if plan['schema_version']!=2:raise ValueError('Repeat groups require schema_version 2')
            if set(item)!={'type','id','name','repeat','on_failure','jobs'}:raise ValueError('Invalid repeat group fields')
            if not all(isinstance(item[k],str) and item[k].strip() for k in ('id','name')):raise ValueError('Invalid group identity')
            if item['id'] in ids:raise ValueError('Duplicate group/job ID')
            ids.add(item['id'])
            if type(item['repeat']) is not int or not 1<=item['repeat']<=10000:raise ValueError('Group repeat must be 1..10000')
            if item['on_failure'] not in ('stop','skip_iteration'):raise ValueError('Invalid group failure policy')
            if not isinstance(item['jobs'],list) or not item['jobs'] or len(item['jobs'])>10000:raise ValueError('Repeat group must contain workflows')
            if any(is_group(child) for child in item['jobs']):raise ValueError('Nested repeat groups are not supported')
            children=item['jobs']; multiplier=item['repeat']
        else:
            children=[item]; multiplier=1
        for j in children:
            validate_job(j,ids)
            total+=j['repeat']*multiplier
        if total*plan['repeat']>10000:raise ValueError('Maximum 10000 expanded steps')
    normalized=deepcopy(plan)
    from .monitor_config import settings
    for job in workflow_jobs(normalized['jobs']):job['monitor']=deepcopy(settings(job))
    return normalized


def validate_job(j,ids):
        if not isinstance(j,dict) or set(j)-{'monitor','fpga_profiles','fpga_id'}!={'id','name','filename','source','sha256','repeat','on_failure','parameters'}:raise ValueError('Invalid Queue job fields')
        from labremote.devices.fpga.mapping import profiles_scope
        with profiles_scope(j.get('fpga_profiles')):pass
        target=target_fpga(j)
        if target is not None and (not isinstance(target,str) or not target.isidentifier()):raise ValueError('Invalid FPGA ID')
        if not all(isinstance(j[k],str) and j[k] for k in ('id','name','filename','source','sha256')):raise ValueError('Invalid workflow identity/source')
        from .monitor_config import settings
        settings(j)
        if j['id'] in ids:raise ValueError('Duplicate job ID')
        ids.add(j['id'])
        if j['on_failure'] not in ('stop','skip') or type(j['repeat']) is not int or not 1<=j['repeat']<=10000:raise ValueError('Invalid repeat/failure policy')
        if not isinstance(j['parameters'],dict):raise ValueError('Parameters must be a JSON object')
        json.dumps(j['parameters'],allow_nan=False)
        if hashlib.sha256(j['source'].encode()).hexdigest()!=j['sha256']:raise ValueError('Workflow source hash mismatch')
        validate_workflow(j['source'],j['filename'])


def expand_steps(plan):
    steps=[]
    def append(j,iteration,group=None,group_iteration=None):
        for repetition in range(j['repeat']):
            step=dict(step_id=f'step_{len(steps)+1:06d}',job_id=j['id'],name=j['name'],
                      iteration=iteration,job_repeat=repetition+1,on_failure=j['on_failure'],status='pending')
            if group is not None:
                step.update(group_id=group['id'],group_name=group['name'],
                            group_iteration=group_iteration,group_repeat=group['repeat'],
                            group_on_failure=group['on_failure'])
            steps.append(step)
    for iteration in range(1,plan['repeat']+1):
        for item in plan['jobs']:
            if is_group(item):
                for group_iteration in range(1,item['repeat']+1):
                    for job in item['jobs']:append(job,iteration,item,group_iteration)
            else:append(item,iteration)
    return steps

def requires_fpga(job):
    import ast
    return bool(job.get('fpga_id') or job.get('parameters',{}).get('fpga') or job.get('fpga_profiles') or
                any(row.get('family')=='fpga' for row in job.get('parameters',{}).get('steps',[]) if isinstance(row,dict))) or any(
        isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='fpga'
        for node in ast.walk(ast.parse(job['source'])))


def target_fpga(job):
    import ast
    names=set()
    for name in (job.get('fpga_id'),job.get('parameters',{}).get('fpga')):
        if name:names.add(name)
    for row in job.get('parameters',{}).get('steps',[]):
        if isinstance(row,dict) and row.get('family')=='fpga' and row.get('device'):names.add(row['device'])
    for node in ast.walk(ast.parse(job['source'])):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='fpga':
            value=node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg=='name'),None)
            if isinstance(value,ast.Constant) and isinstance(value.value,str):names.add(value.value)
    if len(names)>1:raise ValueError('Queue 항목 하나는 FPGA 한 대만 사용할 수 있습니다: '+', '.join(sorted(names)))
    if names:return next(iter(names))
    profiles=job.get('fpga_profiles',{})
    return next(iter(profiles)) if len(profiles)==1 else None


class QueueRunner:
    def __init__(self,bindings,plan,directory,publish=lambda state:None):
        self.bindings=dict(bindings);self.plan=validate_plan(plan);self.directory=tab_data_directory(directory, 'queues');self.publish=publish
        from labremote.devices.fpga.mapping import profiles_from_bindings
        profiles=profiles_from_bindings(self.bindings)
        for job in workflow_jobs(self.plan['jobs']):
            target=target_fpga(job)
            if requires_fpga(job) and target is None:
                raise ValueError(job['name']+': Queue 편집에서 실행 FPGA를 선택하세요.')
            if target:
                job['fpga_id']=target
                frozen=job.get('fpga_profiles',{}).get(target) or profiles.get(target)
                if frozen:job['fpga_profiles']={target:deepcopy(frozen)}
        self.stop=threading.Event();self.pause=threading.Event();self.lock=threading.Lock();self.active=None;self.state=None;self.folder=None
    def cancel(self):
        with self.lock:
            self.stop.set()
            if self.active is not None:self.active.set()
    def pause_after_current(self):self.pause.set()
    def resume(self,bindings=None):
        with self.lock:
            if bindings is not None:self.bindings=dict(bindings)
            self.pause.clear()

    def wait_for_fpga(self,job):
        target=target_fpga(job)
        if target is None:return True
        while not self.stop.is_set():
            with self.lock:bindings=dict(self.bindings)
            worker=next((bridge.worker for family,bridge in bindings.values() if family=='fpga' and bridge.worker.name==target),None)
            reason=''
            if worker is None or worker.ps is None or worker.connection_error or worker._closing or worker._disconnecting:
                reason=target+' 연결 끊김 · 개별 연결 후 계속을 누르세요.'
            elif getattr(worker,'_fpga_owner',None) is not None or worker.has_foreground_requests():
                reason=target+' 사용 중 · 완료 후 계속을 누르세요.'
                with worker._lock:
                    owner=getattr(worker,'_fpga_owner',None)
                    actions=[h.action for h in [worker._active,*worker._pending]
                             if h is not None and not h.done.is_set() and not getattr(h,'automatic_monitor',False)]
                    detail=str(owner) if owner is not None else ', '.join(actions)
                if detail:reason+=' 작업: '+detail
            elif job.get('fpga_profiles',{}).get(target,{}).get('pins',worker.profile.document()['pins']) != worker.profile.document()['pins']:
                reason=target+' 핀 이름이 Queue 저장 시점과 다릅니다. Queue 중지 후 항목을 수정하세요.'
            if not reason:
                if target not in job.get('fpga_profiles',{}):
                    job['fpga_profiles']={target:worker.profile.document()}
                return True
            self.pause.set();self.state.update(status='paused',waiting_reason=reason);self.commit()
            while self.pause.is_set() and not self.stop.wait(.1):pass
            if not self.stop.is_set():self.state.update(status='running',waiting_reason='');self.commit()
        return False
    def commit(self):
        self.state['updated_at']=now();save(self.folder/'queue_manifest.json',self.state);self.publish(deepcopy(self.state))
    def run(self):
        with workflow_session(label='Queue'):return self._run()
    def _run(self):
        from .execution_scope import CURRENT_EXECUTION
        owner=CURRENT_EXECUTION.get()
        self.folder=self.directory/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_queue_'+uuid4().hex);self.folder.mkdir(parents=True,exist_ok=False)
        steps=expand_steps(self.plan)
        self.state=dict(schema_version=1,queue_id=self.folder.name,folder=str(self.folder),status='running',started_at=now(),plan=self.plan,steps=steps,error='')
        self.commit();jobs={j['id']:j for j in workflow_jobs(self.plan['jobs'])};any_failed=False
        try:
            for step in steps:
                if self.stop.is_set():break
                if step['status']!='pending':continue
                if self.pause.is_set():
                    self.state['status']='paused';self.commit()
                    while self.pause.is_set() and not self.stop.wait(.1):pass
                    if self.stop.is_set():break
                    self.state['status']='running';self.commit()
                job=jobs[step['job_id']]
                if not self.wait_for_fpga(job):break
                folder=self.folder/'steps'/step['step_id'];folder.mkdir(parents=True,exist_ok=False)
                (folder/'workflow.py').write_text(job['source'],encoding='utf-8');save(folder/'parameters.json',job['parameters'])
                step.update(status='running',started_at=now(),directory=folder.relative_to(self.folder).as_posix());self.commit()
                started=time.monotonic();local=CancellationToken()
                with self.lock:
                    self.active=local
                    if self.stop.is_set():local.set()
                error_details=''
                try:
                    if local.is_set():raise OperationCancelled('Queue stopped before workflow load')
                    with load_workflow(job['source'],job['filename']) as workflow:
                        context={k:step[k] for k in ('step_id','iteration','job_repeat','group_id','group_name','group_iteration','group_repeat') if k in step}
                        context['queue_id']=self.state['queue_id']
                        save(folder/'queue_context.json',context)
                        target=target_fpga(job)
                        bindings={key:(family,bridge) for key,(family,bridge) in self.bindings.items()
                                  if family!='fpga' or bridge.worker.name==target}
                        result=run_workflow(bindings,workflow,stop_event=local,parameters=job['parameters'],run_directory=str(folder),queue_context=context,fpga_profiles=job.get('fpga_profiles'),fpga_id=target)
                except Exception as exc:
                    error_details=traceback.format_exc()
                    with owner.lock:used_workers=tuple(owner.workers)
                    dangerous=isinstance(exc,(ConnectionError,TimeoutError)) or any(w.connection_error for w in used_workers) or 'timeout' in str(exc).lower() or 'timed out' in str(exc).lower() or 'cleanup' in str(exc).lower() or 'idle state' in str(exc).lower()
                    result=WorkflowResult(status='cancelled' if isinstance(exc,OperationCancelled) else 'failed',reason=f'{type(exc).__name__}: {exc}',continue_allowed=not dangerous,cleanup_status='unknown' if dangerous else 'not_reported')
                finally:
                    with self.lock:self.active=None
                # Final background publication must finish before another workflow starts.
                payload=serializable(result.to_dict());payload['traceback']=error_details
                save(folder/'workflow_result.json',payload)
                summary={k:v for k,v in payload.items() if k not in ('value','traceback')}
                step.update(status=result.status,finished_at=now(),elapsed_s=time.monotonic()-started,result=summary,result_file=(folder/'workflow_result.json').relative_to(self.folder).as_posix())
                any_failed |= result.status=='failed';self.commit()
                if result.status=='cancelled':self.stop.set();break
                if result.status=='failed':
                    if not result.continue_allowed or result.cleanup_status in ('failed','unknown'):break
                    if 'group_id' in step:
                        if step['group_on_failure']=='stop':break
                        # Skip the rest of this cycle, never run entanglement after failed SPAM.
                        for remaining in steps:
                            if (remaining['status']=='pending' and
                                    all(remaining.get(k)==step[k] for k in ('iteration','group_id','group_iteration'))):
                                remaining.update(status='skipped',reason='Earlier workflow failed in this group iteration')
                        self.commit()
                    elif job['on_failure']=='stop':break
            terminal='cancelled' if self.stop.is_set() else 'failed' if any_failed else 'completed'
            for step in steps:
                if step['status']=='pending':step.update(status='cancelled',reason='Queue ended before this step')
            self.state.update(status=terminal,finished_at=now());self.commit();return deepcopy(self.state)
        except Exception as exc:
            # A manifest/storage failure stops execution, regardless of Skip.
            for step in steps:
                if step['status']=='running':step.update(status='failed',reason=str(exc))
                elif step['status']=='pending':step.update(status='cancelled',reason='Queue infrastructure failure')
            self.state.update(status='failed',error=f'{type(exc).__name__}: {exc}',finished_at=now())
            try:self.commit()
            except Exception:pass
            raise
