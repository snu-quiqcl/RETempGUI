"""Exclusive acquisition, strict FIFO protocol and unconditional output cleanup."""
import threading
import time
from datetime import datetime
from labremote.runtime.errors import OperationCancelled
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram
from .config import CLEANUP_LEVELS, OUTPUTS, hd, nominal_trials
from .sequence import build_program


class CleanupError(ConnectionError):
    pass


def cleanup(controller, c):
    if controller.device is None:
        raise CleanupError('FPGA disconnected; output cleanup unconfirmed')
    controller.device.stop_sequencer()
    s = SequencerProgram()
    ports = {}
    for name, level in CLEANUP_LEVELS.items():
        _, port, bit = OUTPUTS[name]
        ports.setdefault(port, []).append((bit, level))
    # Stop all photon counters, including interrupted state readout.
    s.set_output_port(hd.counter_control_port,
        [(getattr(hd, name+'_counter_enable'),0) for name in hd.input_mapping.values()
         if hasattr(hd,name+'_counter_enable')])
    for port, values in sorted(ports.items()):
        s.set_output_port(port, values)
    s.stop()
    controller.device.auto_mode()
    controller._run(s, 0, threading.Event())


def decode(rows, c):
    if len(rows) != 163 or any(not isinstance(r,(list,tuple)) or len(r)!=4 or
            any(type(v) is not int or not 0<=v<=65535 for v in r) for r in rows):
        raise ValueError('Incomplete or malformed entanglement FIFO')
    if [r[3] for r in rows] != [100]*162+[101]:
        raise ValueError('Unexpected entanglement FIFO tags')
    if rows[-1][1:3] != [2,0] or rows[-1][0] not in (0,1):
        raise ValueError('Unknown entanglement FIFO version')
    if rows[-1][0]:
        raise OverflowError('16-bit histogram saturated; reduce attempts per batch')
    flat = [v for row in rows[:162] for v in row[:3]]
    a, b, coin = flat[:120], flat[120:240], flat[240:480]
    ea, ec, group, loop, herald, inner = flat[480:]
    if herald not in (0,1):
        raise ValueError('Invalid herald flag')
    if herald:
        if not (group<c['groups_per_loop'] and loop<c['fpga_loops'] and inner<c['inner_trials']):
            raise ValueError('Invalid attempt indices')
        attempts=(loop*c['groups_per_loop']+group)*c['inner_trials']+inner+1
    else:
        if [ea,ec,group,loop,inner] != [0,0,0,c['fpga_loops'],0]:
            raise ValueError('Invalid exhausted-batch counters')
        attempts=nominal_trials(c)
    accepted=sum(coin[120-c['coincidence_half_window_bins']:120+c['coincidence_half_window_bins']])
    if accepted != herald or sum(a)>attempts or sum(b)>attempts or sum(coin)>min(sum(a),sum(b)):
        raise ValueError('Inconsistent histogram / herald counts')
    return dict(a=a,c=b,coincidence=coin,attempts=attempts,heralded=bool(herald),
        outcome='heralded' if herald else 'max_attempts_reached',
        state_counts=dict(ea=ea,ec=ec) if herald else None,
        state_label=(str(int(ea>c['threshold_ea']))+str(int(ec>c['threshold_ec']))) if herald else None,
        indices=dict(group=group,fpga_loop=loop,inner_trial=inner),state_words=flat[480:])


def run(controller, c, cancelled, on_rows, on_batch, on_cleanup=lambda status: None, on_event=lambda event: None):
    controller._idle(); d = controller.device
    expected = 163
    def check():
        if cancelled.is_set():raise OperationCancelled('Entanglement cancelled')
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
                    if time.perf_counter()>deadline:raise TimeoutError('Entanglement batch timeout')
                    status=timed('status_poll',d.sequencer_running_status)
                    if status not in ('running','stopped'):raise ValueError('Invalid sequencer status')
                    available=timed('status_poll',length)
                    while available:
                        check()
                        if time.perf_counter()>deadline:raise TimeoutError('Entanglement FIFO timeout')
                        size=min(available,500); values=timed('fifo_read',d.read_fifo_data,size)
                        received_at=stamp(); record['last_fifo_received_at']=received_at
                        if record['first_fifo_received_at'] is None:record['first_fifo_received_at']=received_at
                        record['received_fifo_rows']+=len(values) if isinstance(values,list) else 1
                        good=isinstance(values,list) and len(values)==size and len(rows)+size<=expected and all(isinstance(r,(list,tuple)) and len(r)==4 and all(type(v) is int and 0<=v<=65535 for v in r) for r in values)
                        on_rows(batch,values,good)
                        if not good:raise ValueError('Invalid Entanglement FIFO payload')
                        rows.extend([list(r) for r in values]); available-=size
                    if status=='stopped':break
                    time.sleep(.001)
                check()
                data=decode(rows,c)
                on_batch(dict(data,batch=batch,elapsed_s=time.perf_counter()-clock,sequence_elapsed_s=time.perf_counter()-start))
                record['status']='completed'
            except BaseException as exc:
                record['status']='aborted' if isinstance(exc,OperationCancelled) else 'failed'
                # Stop hardware BEFORE checkpoint/fsync; full cleanup follows below.
                try:d.stop_sequencer()
                except Exception as stop_error:record['stop_error']=str(stop_error)
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
            raise CleanupError(f'Entanglement cleanup failed: {exc}; original: {original}') from exc
        on_cleanup('completed')
        raise
    else:
        try:cleanup(controller,c)
        except Exception as exc:
            on_cleanup('failed')
            raise CleanupError(f'Entanglement cleanup failed: {exc}') from exc
        on_cleanup('completed')
