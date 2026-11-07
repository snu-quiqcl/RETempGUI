"""Distinguish automatic reads from foreground work before starting a Queue."""
import time
from contextlib import nullcontext
from .errors import OperationCancelled


def request_description(handle):
    text=f"{getattr(handle,'action','unknown request')} [{getattr(handle,'status','unknown')}]"
    request_id=getattr(handle,'request_id',None)
    if request_id:text+=' request='+str(request_id)
    location=getattr(handle,'location','')
    if location:text+=' at '+str(location)
    return text


def activity(bindings):
    """Take snapshots under owning locks, never query or cancel hardware."""
    from .workflow_runner import _TASK_LOCK
    workers={}
    for alias,(_,bridge) in bindings.items():workers.setdefault(bridge.worker,[]).append(str(alias))
    blockers=[];polls=[]
    for worker,aliases in workers.items():
        name=getattr(worker,'name',None)
        device=', '.join(sorted(aliases))
        if name and name not in aliases:device+=' ('+str(name)+')'
        family=getattr(worker,'family',None)
        if family:device+=' / '+str(family)
        with getattr(worker,'_lock',nullcontext()):
            if hasattr(worker,'_pending'):
                handles=list(worker._pending)+[getattr(worker,'_active',None)]
                unknown=False
            else:
                legacy=getattr(worker,'_handles',{})
                handles=list(legacy.values()) if isinstance(legacy,dict) else list(legacy)
                unknown=not handles and hasattr(worker,'has_requests') and worker.has_requests()
            unique={id(h):h for h in handles if h is not None and not h.done.is_set()}
        if unknown:blockers.append(device+': pending device request (details unavailable)')
        for handle in unique.values():
            description=device+': '+request_description(handle)
            if getattr(handle,'automatic_monitor',False):polls.append((handle,description))
            else:blockers.append(description)
        with _TASK_LOCK:tasks=tuple(getattr(worker,'_background_tasks',()))
        for task in tasks:
            if task.running():
                handle=getattr(task,'handle',None)
                text=request_description(handle) if handle is not None else str(getattr(task,'label',type(task).__name__))
                blockers.append(device+': background '+text+' (running / stopping)')
        repeat=getattr(worker,'waveform_runner',None)
        if repeat is not None and repeat.running():
            handle=getattr(repeat,'handle',None)
            blockers.append(device+': waveform/repeat '+(request_description(handle) if handle is not None else 'running / stopping'))
    return blockers,polls


def wait_until_ready(bindings,stop,timeout_s=22.):
    """Caller holds AUTO_MONITOR.workflow(), so no new automatic read can begin.

    Drain already submitted reads before submitting any Queue operation. Real
    foreground work is never cancelled or ignored. A stalled read remains a
    named blocker rather than allowing concurrent device access.
    """
    deadline=time.monotonic()+timeout_s
    observed={}
    while True:
        if stop.is_set():raise OperationCancelled('Queue cancelled while waiting for automatic polling')
        blockers,polls=activity(bindings)
        if blockers:
            raise RuntimeError('Finish active device tasks before starting Queue:\n'+'\n'.join('- '+b for b in blockers))
        for handle,description in polls:observed[id(handle)]=(handle,description)
        errors=[description+': '+str(handle.error) for handle,description in observed.values() if handle.done.is_set() and handle.error is not None]
        if errors:
            raise RuntimeError('Automatic polling failed before Queue start; check device connection:\n'+'\n'.join('- '+e for e in errors))
        if not polls:return
        if time.monotonic()>=deadline:
            raise RuntimeError(f'Automatic polling did not finish within {timeout_s:g}s; Queue was not started:\n'+'\n'.join('- '+description for _,description in polls))
        stop.wait(min(.05,max(0,deadline-time.monotonic())))
