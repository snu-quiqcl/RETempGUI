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

def freeze_job(filename,*,name=None,repeat=1,on_failure='stop',parameters=None):
    path=Path(filename).resolve();source=path.read_text(encoding='utf-8-sig');validate_workflow(source,str(path))
    return dict(id=uuid4().hex,name=name or path.stem,filename=str(path),source=source,sha256=hashlib.sha256(source.encode()).hexdigest(),repeat=repeat,on_failure=on_failure,parameters=deepcopy(parameters or {}))

def validate_plan(plan):
    if not isinstance(plan,dict) or plan.get('schema_version')!=1:raise ValueError('Queue schema_version must be 1')
    if type(plan.get('repeat')) is not int or not 1<=plan['repeat']<=10000:raise ValueError('Queue repeat must be 1..10000')
    jobs=plan.get('jobs')
    if not isinstance(jobs,list) or not jobs or len(jobs)>10000:raise ValueError('Add at least one workflow (maximum 10000)')
    ids=set()
    for j in jobs:
        if not isinstance(j,dict) or set(j)!={'id','name','filename','source','sha256','repeat','on_failure','parameters'}:raise ValueError('Invalid Queue job fields')
        if not all(isinstance(j[k],str) and j[k] for k in ('id','name','filename','source','sha256')):raise ValueError('Invalid workflow identity/source')
        if j['id'] in ids:raise ValueError('Duplicate job ID')
        ids.add(j['id'])
        if j['on_failure'] not in ('stop','skip') or type(j['repeat']) is not int or not 1<=j['repeat']<=10000:raise ValueError('Invalid repeat/failure policy')
        if not isinstance(j['parameters'],dict):raise ValueError('Parameters must be a JSON object')
        json.dumps(j['parameters'],allow_nan=False)
        if hashlib.sha256(j['source'].encode()).hexdigest()!=j['sha256']:raise ValueError('Workflow source hash mismatch')
        validate_workflow(j['source'],j['filename'])
    if sum(j['repeat'] for j in jobs)*plan['repeat']>10000:raise ValueError('Maximum 10000 expanded steps')
    return deepcopy(plan)

class QueueRunner:
    def __init__(self,bindings,plan,directory,publish=lambda state:None):
        self.bindings=dict(bindings);self.plan=validate_plan(plan);self.directory=Path(directory).resolve();self.publish=publish
        self.stop=threading.Event();self.pause=threading.Event();self.lock=threading.Lock();self.active=None;self.state=None;self.folder=None
    def cancel(self):
        with self.lock:
            self.stop.set()
            if self.active is not None:self.active.set()
    def pause_after_current(self):self.pause.set()
    def resume(self):self.pause.clear()
    def commit(self):
        self.state['updated_at']=now();save(self.folder/'queue_manifest.json',self.state);self.publish(deepcopy(self.state))
    def run(self):
        from .auto_monitor import AUTO_MONITOR
        with workflow_session(),AUTO_MONITOR.workflow():return self._run()
    def _run(self):
        workers={bridge.worker for _,bridge in self.bindings.values()}
        # Do not begin a queue in the middle of an independently started task.
        for w in workers:
            if (w.has_requests() if hasattr(w,'has_requests') else bool(getattr(w,'_handles',{}))) or any(t.running() for t in w._background_tasks) or (getattr(w,'waveform_runner',None) is not None and w.waveform_runner.running()):raise RuntimeError('Finish active device tasks before starting Queue')
        self.folder=self.directory/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_queue_'+uuid4().hex);self.folder.mkdir(parents=True,exist_ok=False)
        steps=[]
        for iteration in range(self.plan['repeat']):
            for j in self.plan['jobs']:
                for repetition in range(j['repeat']):
                    steps.append(dict(step_id=f'step_{len(steps)+1:06d}',job_id=j['id'],name=j['name'],iteration=iteration+1,job_repeat=repetition+1,on_failure=j['on_failure'],status='pending'))
        self.state=dict(schema_version=1,queue_id=self.folder.name,folder=str(self.folder),status='running',started_at=now(),plan=self.plan,steps=steps,error='')
        self.commit();jobs={j['id']:j for j in self.plan['jobs']};any_failed=False
        try:
            for step in steps:
                if self.stop.is_set():break
                if self.pause.is_set():
                    self.state['status']='paused';self.commit()
                    while self.pause.is_set() and not self.stop.wait(.1):pass
                    if self.stop.is_set():break
                    self.state['status']='running';self.commit()
                job=jobs[step['job_id']];folder=self.folder/'steps'/step['step_id'];folder.mkdir(parents=True,exist_ok=False)
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
                        result=run_workflow(self.bindings,workflow,stop_event=local,parameters=job['parameters'],run_directory=str(folder),queue_context={k:step[k] for k in ('step_id','iteration','job_repeat')}|{'queue_id':self.state['queue_id']})
                except Exception as exc:
                    error_details=traceback.format_exc()
                    dangerous=isinstance(exc,(ConnectionError,TimeoutError)) or any(w.connection_error for w in workers) or 'timeout' in str(exc).lower() or 'timed out' in str(exc).lower() or 'cleanup' in str(exc).lower() or 'idle state' in str(exc).lower()
                    result=WorkflowResult(status='cancelled' if isinstance(exc,OperationCancelled) else 'failed',reason=f'{type(exc).__name__}: {exc}',continue_allowed=not dangerous,cleanup_status='unknown' if dangerous else 'not_reported')
                finally:
                    with self.lock:self.active=None
                # Final background publication must finish before another workflow starts.
                from .characterization_guard import join_completed
                join_completed(workers)
                payload=serializable(result.to_dict());payload['traceback']=error_details
                save(folder/'workflow_result.json',payload)
                summary={k:v for k,v in payload.items() if k not in ('value','traceback')}
                step.update(status=result.status,finished_at=now(),elapsed_s=time.monotonic()-started,result=summary,result_file=(folder/'workflow_result.json').relative_to(self.folder).as_posix())
                any_failed |= result.status=='failed';self.commit()
                if result.status=='cancelled':self.stop.set();break
                if result.status=='failed' and (job['on_failure']=='stop' or not result.continue_allowed or result.cleanup_status in ('failed','unknown')):break
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
