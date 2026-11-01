"""Workflow outcome contract, compatible with legacy main(devices) functions."""
from dataclasses import dataclass,field,asdict
from contextlib import contextmanager
import threading

_EXECUTION_LOCK=threading.RLock()

@contextmanager
def workflow_session():
    if not _EXECUTION_LOCK.acquire(blocking=False):raise RuntimeError('Another workflow or Queue is active')
    try:yield
    finally:_EXECUTION_LOCK.release()

@dataclass
class WorkflowResult:
    status:str='completed'
    reason:str=''
    result_paths:list=field(default_factory=list)
    metrics:dict=field(default_factory=dict)
    cleanup_status:str='not_reported'
    continue_allowed:bool=True
    value:object=None
    def to_dict(self):return asdict(self)

def normalize(value):
    if isinstance(value,WorkflowResult):result=value
    elif isinstance(value,dict) and 'status' in value:
        status={'success':'completed','complete':'completed'}.get(value['status'],value['status'])
        result=WorkflowResult(status=status,reason=str(value.get('reason') or value.get('error') or ''),result_paths=value.get('result_paths') or ([value['folder']] if value.get('folder') else []),metrics=value.get('metrics',{}),cleanup_status=value.get('cleanup_status','not_reported'),continue_allowed=value.get('continue_allowed',True),value=value)
    else:result=WorkflowResult(value=value)
    if result.status not in ('completed','failed','cancelled'):raise ValueError('Workflow result status must be completed, failed, or cancelled')
    if not isinstance(result.result_paths,list) or not all(isinstance(p,str) for p in result.result_paths):raise ValueError('result_paths must be a list of strings')
    if not isinstance(result.metrics,dict) or type(result.continue_allowed) is not bool:raise ValueError('Invalid workflow metrics/continue_allowed')
    if result.cleanup_status not in ('completed','not_required','not_reported','failed','unknown'):raise ValueError('Invalid cleanup_status')
    if result.status=='completed' and result.cleanup_status in ('failed','unknown'):
        result.status='failed'
        result.reason=result.reason or 'Workflow cleanup was not confirmed'
    return result
