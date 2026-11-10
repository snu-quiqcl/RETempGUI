"""Retire completed publishers before sequential experiment starts."""
from .workflow_runner import _TASK_LOCK

def join_completed(workers):
    # A handle can finish just before its publisher thread exits. Sequential
    # workflow .wait() calls must not mistake that final publication for new work.
    with _TASK_LOCK:tasks={t for w in workers for t in w._background_tasks}
    for task in tasks:
        if getattr(task,'exclusive_fpga',False) and task.handle is not None and task.handle.done.is_set():task.join()

def enqueue(worker,handle,submit):
    # All FPGA commands use the ordinary operation FIFO.
    return submit(handle)
