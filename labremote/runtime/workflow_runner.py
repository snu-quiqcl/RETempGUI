from labremote.runtime.jobs import WorkflowGroup
from labremote.api.devices import Devices
from types import SimpleNamespace

def run_workflow(bindings, workflow, *, on_event=None, stop_event=None, parameters=None, run_directory=None, queue_context=None):
    from .workflow_result import workflow_session
    with workflow_session():
        return _run_workflow(bindings, workflow, on_event=on_event, stop_event=stop_event, parameters=parameters, run_directory=run_directory, queue_context=queue_context)


def _run_workflow(bindings, workflow, *, on_event=None, stop_event=None, parameters=None, run_directory=None, queue_context=None):
    group = WorkflowGroup(stop_event, on_event)
    devices = Devices(bindings, group=group)
    from copy import deepcopy
    devices.parameters=deepcopy(parameters or {})
    devices.run_directory=run_directory
    devices.queue_context=deepcopy(queue_context or {})
    try:
        if group.stop.is_set():raise OperationCancelled("Workflow cancelled before execution")
        value=workflow(devices)
        group.finish()
        from .workflow_result import normalize
        return normalize(value)
    except BaseException:
        try: group.finish(failed=True)
        except Exception: pass
        raise


# Long-running built-in workflows use the same handles and per-device queues.
import threading
from copy import deepcopy
from labremote.runtime.jobs import ExecutionHandle
from labremote.runtime.errors import OperationCancelled

_TASK_LOCK=threading.RLock()


def motor_identity(worker):
    if worker.family!='motors':return None
    return worker._execution_device or ('worker',id(worker))


def conflicting_scan(participants):
    keys={motor_identity(w) for w in participants}-{None}
    tasks={task for w in participants for task in w._background_tasks}
    return any(task.label in ('MOTOR_SCAN','MOTOR_GOTO_MAX') and task.running() and
               keys.intersection(motor_identity(w) for w in task.participants)
               for task in tasks)


class TaskHandle(ExecutionHandle):
    def request_cancel(self):
        from contextlib import nullcontext
        lock=getattr(self.group.stop,"lock",None)
        with lock if lock is not None else nullcontext():
            with self._lock:
                if self.done.is_set():return False
                self.cancel_event.set();self.group.stop.set();self.status='stopping'
        self.notify();return True
    def cancel(self):return self.request_cancel()


class WorkflowTask:
    def __init__(self,worker,label):
        self.worker,self.label=worker,label
        self.handle=None;self.thread=None;self.state={};self.state_lock=threading.RLock()
        self.participants=();self.group=None

    def running(self):return self.thread is not None and self.thread.is_alive()

    def launch(self,callback,participants,settings,parent=None,*,owned_participants=None,shared_participants=()):
        with _TASK_LOCK:
            group=WorkflowGroup(stop=parent.stop if parent is not None else None)
            if parent is not None:group.owner=parent.owner;group.owns_execution=False
            group.shared_workers=set(shared_participants)
            if group.owns_execution:group.owner.label=self.label
            handle=TaskHandle(self.label,None,group)
            if self.label=='MOTOR_SCAN':handle.arguments={'scan':settings['scan']}
            group.task_run_id=handle.request_id
            group.scan_number=settings.get('scan') if self.label=='MOTOR_SCAN' else None
            error=None
            if self.running():error=RuntimeError(self.label+' is already running or stopping')
            elif any(w._closing or w.ps is None or w.connection_error for w in participants):error=ConnectionError('Connect all participating devices first')
            elif any(getattr(t,'exclusive_fpga',False) and t.running() and not t.handle.done.is_set() for w in participants for t in w._background_tasks):error=RuntimeError('FPGA reserved by daily characterization')
            elif self.label=='MOTOR_SCAN' and conflicting_scan(participants):error=RuntimeError('A participating device already belongs to a scan')
            elif self.label=='MOTOR_SCAN' and self.worker.waveform_runner.running():error=RuntimeError('Stop FPGA repeat measurement before scanning')
            if parent is not None:parent.add(handle)
            claimed=[]
            if error is None:
                try:
                    for w in (participants if owned_participants is None else owned_participants):
                        if w.reserve_execution(group.owner,shared=w in group.shared_workers):claimed.append(w)
                except Exception as exc:
                    error=exc
                    for w in claimed:w.release_execution(group.owner)
            if error is not None:
                if parent is not None:parent.stop.set()
                handle.finish(error);self.worker.task_changed.emit(self.label,handle);self.worker.failure.emit(self.label,str(error));return handle
            for previous in self.participants:previous._background_tasks.discard(self)
            self.handle,self.group,self.participants=handle,group,tuple(participants)
            for name in ('cleanup_group','fpga_cleanup_group'):
                cleanup=getattr(self,name,None)
                if cleanup is not None:cleanup.owner=group.owner;cleanup.owns_execution=False
            self.child_failed=False;self.settings=deepcopy(settings);self.state={'run_id':handle.request_id}
            if self.label=='MOTOR_SCAN':self.state['scan']=settings['scan']
            for w in participants:w._background_tasks.add(self)
            handle.subscribe(lambda h:self.worker.task_changed.emit(self.label,h))
            self.thread=threading.Thread(target=self._run,args=(callback,handle),name=self.label+'-'+str(self.worker.name))
            self.thread.start();return handle

    def _run(self,callback,handle):
        from .execution_scope import execution_scope
        try:
            with execution_scope(self.group.owner):self._run_owned(callback,handle)
        finally:
            if self.group.owns_execution:self.group.owner.release()

    def _run_owned(self,callback,handle):
        error=None;value=None;record=None
        try:
            self.check();handle.status='running';handle.notify()
            from labremote.runtime.recording import RunRecord
            record=RunRecord(self.label,{'request_id':handle.request_id,'settings':self.settings,'devices':[w.name for w in self.participants]})
            value=callback();self.check()
        except Exception as exc:
            error=exc;self.group.stop.set()
        finally:
            if record is not None:
                try:record.finish(value=value,error=error)
                except Exception as exc:self.worker.failure.emit('LOG',str(exc))
            error=handle.finish(error,result=value)
            self.publish(status=handle.status,error=str(error) if error else '')
            if error is not None and not self.child_failed:self.worker.failure.emit(self.label,f'{type(error).__name__}: {error}\nRequest: {handle.request_id}')

    def call(self,handle):
        try:return handle.wait()
        except Exception:
            self.child_failed=True;raise
        finally:
            with self.group.lock:
                if handle in self.group.handles:self.group.handles.remove(handle)

    def check(self):
        self.handle.check_cancelled()
        if any(w._closing or w.ps is None or w.connection_error for w in self.participants):raise ConnectionError('A participating device disconnected')

    def wait(self,seconds):
        self.check()
        if self.group.stop.wait(seconds):self.check()
        self.check()

    def publish(self,**changes):
        with self.state_lock:self.state.update(changes);snapshot=deepcopy(self.state)
        self.worker.task_progress.emit(self.label,snapshot)

    def cancel(self):
        if self.handle is not None:self.handle.request_cancel()
        return self.handle

    def join(self):
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join()
            with _TASK_LOCK:
                for w in self.participants:w._background_tasks.discard(self)
