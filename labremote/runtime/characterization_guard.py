"""Reserve existing FPGA/microwave queues during a characterization run."""
from .workflow_runner import _TASK_LOCK

def join_completed(workers):
    # A handle can finish just before its publisher thread exits. Sequential
    # workflow .wait() calls must not mistake that final publication for new work.
    with _TASK_LOCK:tasks={t for w in workers for t in w._background_tasks}
    for task in tasks:
        if getattr(task,'exclusive_fpga',False) and task.handle is not None and task.handle.done.is_set():task.join()

def enqueue(worker,handle,submit):
    with _TASK_LOCK:
        for task in worker._background_tasks:
            if not getattr(task,'exclusive_fpga',False) or not task.running() or task.handle.done.is_set():continue
            owners=(task.group,getattr(task,'cleanup_group',None),getattr(task,'fpga_cleanup_group',None))
            if (handle.group is not None and any(handle.group is owner for owner in owners)) or handle.action=='DISCONNECT':continue
            error=RuntimeError('Device reserved by '+task.label)
            if handle.group is not None:handle.group.stop.set()
            handle.finish(error);worker.handle_changed.emit(handle);return handle
        return submit(handle)
