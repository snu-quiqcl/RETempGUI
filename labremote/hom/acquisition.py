"""Exclusive acquisition, strict FIFO protocol and unconditional output cleanup."""
import threading
import time
from datetime import datetime
from labremote.runtime.errors import OperationCancelled
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram
from .config import outputs, auxiliary, nominal_trials
from .sequence import build_program


class CleanupError(ConnectionError):
    pass


def cleanup(controller, c):
    if controller.device is None:
        raise CleanupError('FPGA disconnected; output cleanup unconfirmed')
    controller.device.stop_sequencer()
    s = SequencerProgram()
    outputs(s, c, dict(TRIG=0, AOMA=1, AOMC=1))
    auxiliary(s, c, False)
    s.stop()
    controller.device.auto_mode()
    controller._run(s, 0, threading.Event())


def decode(rows, c):
    m = c['MAX_TIME_DIFFERENCE']; n = 4*m//3
    if len(rows) != n+3 or [r[3] for r in rows] != [100]*n+[101,102,103]:
        raise ValueError('Incomplete or unordered HOM FIFO tags')
    valid = sum(rows[n][i] << (16*i) for i in range(3))
    missing = sum(rows[n+1][i] << (16*i) for i in range(3))
    if rows[-1][1:] != [1,0,103] or rows[-1][0] not in (0,1):
        raise ValueError('Unknown HOM protocol metadata')
    if valid+missing != nominal_trials(c):
        raise ValueError('HOM trial counters do not match configured execution')
    if rows[-1][0]:
        raise OverflowError('16-bit HOM histogram saturated; reduce trials per batch')
    flat = [v for row in rows[:n] for v in row[:3]]
    a, b, h = flat[:m], flat[m:2*m], flat[2*m:]
    if sum(a)>valid or sum(b)>valid or sum(h)>min(sum(a),sum(b)):
        raise ValueError('Inconsistent HOM histogram counts')
    if not valid:
        raise ValueError('No valid SYNC trials; check SYNC input')
    return dict(a=a, c=b, hom=h, trials=valid, missing_sync=missing)


def run(controller, c, cancelled, on_rows, on_batch, on_cleanup=lambda status: None, on_event=lambda event: None):
    controller._idle(); d = controller.device
    expected = 4*c['MAX_TIME_DIFFERENCE']//3+3
    def check():
        if cancelled.is_set():raise OperationCancelled('HOM cancelled')
    def length():
        n = d.fifo_data_length()
        if type(n) is not int or not 0<=n<=65535:raise ValueError('Invalid FIFO length')
        return n
    try:
        check(); cleanup(controller,c)
        for batch in range(c['batches']):
            check()
            clock=time.perf_counter()
            stamp=lambda: datetime.now().astimezone().isoformat(timespec='milliseconds')
            record=dict(batch=batch,status='running',started_at=stamp(),finished_at=None,
                upload_started_at=None,upload_finished_at=None,sequencer_started_at=None,
                first_fifo_received_at=None,last_fifo_received_at=None,elapsed_s=0.,
                programmed_trials=nominal_trials(c),received_fifo_rows=0,expected_fifo_rows=expected,
                timings_s=dict(upload=0.,start_commands=0.,status_poll=0.,fifo_read=0.,stale_flush=0.),error='')
            def timed(key,fn,*args,**kwargs):
                tick=time.perf_counter()
                try:return fn(*args,**kwargs)
                finally:record['timings_s'][key]+=time.perf_counter()-tick
            try:
                on_event(dict(record,event='started'))
                stale=timed('stale_flush',length)
                while stale:
                    check(); size=min(stale,500); timed('stale_flush',d.read_fifo_data,size); stale-=size
                program=build_program(c); record['upload_started_at']=stamp()
                timed('upload',program.program,show=False,target=d); record['upload_finished_at']=stamp()
                check(); timed('start_commands',d.auto_mode); timed('start_commands',d.start_sequencer)
                record['sequencer_started_at']=stamp()
                rows=[]; start=time.perf_counter(); deadline=start+c['timeout_s']
                while True:
                    check()
                    if time.perf_counter()>deadline:raise TimeoutError('HOM batch timeout')
                    status=timed('status_poll',d.sequencer_running_status)
                    if status not in ('running','stopped'):raise ValueError('Invalid sequencer status')
                    available=timed('status_poll',length)
                    while available:
                        check()
                        if time.perf_counter()>deadline:raise TimeoutError('HOM FIFO timeout')
                        size=min(available,500); values=timed('fifo_read',d.read_fifo_data,size)
                        received_at=stamp(); record['last_fifo_received_at']=received_at
                        if record['first_fifo_received_at'] is None:record['first_fifo_received_at']=received_at
                        record['received_fifo_rows']+=len(values) if isinstance(values,list) else 1
                        good=isinstance(values,list) and len(values)==size and len(rows)+size<=expected and all(isinstance(r,(list,tuple)) and len(r)==4 and all(type(v) is int and 0<=v<=65535 for v in r) for r in values)
                        on_rows(batch,values,good)
                        if not good:raise ValueError('Invalid HOM FIFO payload')
                        rows.extend([list(r) for r in values]); available-=size
                    if status=='stopped':break
                    time.sleep(.001)
                data=decode(rows,c)
                on_batch(dict(data,batch=batch,elapsed_s=time.perf_counter()-start))
                record['status']='completed'
            except BaseException as exc:
                record['status']='cancelled' if isinstance(exc,OperationCancelled) else 'failed'
                record['error']=f'{type(exc).__name__}: {exc}'
                raise
            finally:
                record.update(finished_at=stamp(),elapsed_s=time.perf_counter()-clock)
                record['timings_s']['communication_calls']=sum(record['timings_s'].values())
                on_event(dict(record,event='finished'))
    except BaseException as original:
        try:cleanup(controller,c)
        except Exception as exc:
            on_cleanup('failed')
            raise CleanupError(f'HOM cleanup failed: {exc}; original: {original}') from exc
        on_cleanup('completed')
        raise
    else:
        try:cleanup(controller,c)
        except Exception as exc:
            on_cleanup('failed')
            raise CleanupError(f'HOM cleanup failed: {exc}') from exc
        on_cleanup('completed')
