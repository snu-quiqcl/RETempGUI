"""Workflow context for cancellation diagnostics; never reserves hardware."""
from contextlib import contextmanager
from contextvars import ContextVar
import threading
from uuid import uuid4

CURRENT_EXECUTION=ContextVar('execution_scope',default=None)
class ExecutionOwner:
    def __init__(self,label='Workflow'):
        self.label=label;self.id=uuid4().hex;self.lock=threading.RLock();self.workers=set()
    def remember(self,worker):
        with self.lock:self.workers.add(worker)
    def release(self):
        with self.lock:self.workers.clear()
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
