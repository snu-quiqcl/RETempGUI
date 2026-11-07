"""Execution identity only; workers enforce ownership of their own device."""
from contextlib import contextmanager
from contextvars import ContextVar
import threading
from uuid import uuid4

CURRENT_EXECUTION=ContextVar('execution_scope',default=None)
_registry_lock=threading.RLock()
_reservations={}
_shared={}

def identity(worker):
    key=getattr(worker,'_execution_device',None)
    if not key:return ('worker',id(worker))
    if key[0]=='serial':return tuple(key)
    from .ownership import device_id
    try:return device_id(*key)
    except (TypeError,ValueError):return tuple(key)  # local adapters have opaque IDs

def owner_for(worker):
    with _registry_lock:return _reservations.get(identity(worker))

def claim(worker,owner,shared=False):
    from .errors import ResourceBusy
    with _registry_lock:
        key=identity(worker);current=_reservations.get(key)
        if current is not None and current is not owner:
            raise ResourceBusy(f'{worker.name or worker.family}: device reserved by {current}')
        others=_shared.get(key,set())-{owner}
        if not shared and others:raise ResourceBusy(f'{worker.name or worker.family}: device shared by '+', '.join(map(str,others)))
        if shared:_shared.setdefault(key,set()).add(owner)
        else:_reservations[key]=owner

def shared_owners(worker):
    with _registry_lock:return set(_shared.get(identity(worker),()))

def release(worker,owner):
    with _registry_lock:
        key=identity(worker)
        if _reservations.get(key) is owner:del _reservations[key]
        if key in _shared:
            _shared[key].discard(owner)
            if not _shared[key]:del _shared[key]

class ExecutionOwner:
    def __init__(self,label='Workflow'):
        self.label=label;self.id=uuid4().hex;self.lock=threading.RLock();self.workers=set()
    def remember(self,worker):
        with self.lock:self.workers.add(worker)
    def release(self):
        with self.lock:workers=tuple(self.workers);self.workers.clear()
        for worker in workers:worker.release_execution(self)
        # A workflow may reconnect a worker under a different endpoint/name.
        with _registry_lock:
            for key in list(_reservations):
                if _reservations[key] is self:del _reservations[key]
            for key in list(_shared):
                _shared[key].discard(self)
                if not _shared[key]:del _shared[key]
    def __str__(self):return f'{self.label} ({self.id[:8]})'

@contextmanager
def execution_scope(owner=None,label='Workflow'):
    previous=CURRENT_EXECUTION.get()
    created=owner is None and previous is None
    owner=owner or previous or ExecutionOwner(label)
    token=CURRENT_EXECUTION.set(owner)
    try:yield owner
    finally:
        CURRENT_EXECUTION.reset(token)
        if created:owner.release()
