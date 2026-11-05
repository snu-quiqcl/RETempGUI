"""Exclusive decay acquisition: one FPGA run per PC batch, with cleanup."""
import threading
import time
from datetime import datetime
from labremote.runtime.errors import OperationCancelled
from labremote.decay.config import hardware,set_auxiliary
from labremote.decay.sequence import build_program
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram

def cleanup(controller,c):
    d=controller.device
    if d is None:raise RuntimeError('FPGA disconnected; cleanup not confirmed')
    h=hardware(c);d.stop_sequencer();s=SequencerProgram()
    pins=[(h.TRIG_out,0),(h.AOM_out,1)]
    if c['mode'].startswith('171'):pins += [(h.EOM_7G1_out,1),(h.EOM_7G2_out,1),(h.EOM_2G_out,0)]
    s.set_output_port(h.external_control_port,pins);set_auxiliary(s,c,start=False);s.stop();d.auto_mode();controller._run(s,0,threading.Event())

def run(controller,c,cancelled,on_rows,on_chunk,on_batch=None):
    controller._idle();d=controller.device
    channels=2 if c['mode'].endswith('dual') else 1;bins=c['MAX_TIME_DIFFERENCE'];expected=channels*bins//3
    def check():
        if cancelled.is_set():raise OperationCancelled('Decay cancelled')
    def length():
        n=d.fifo_data_length()
        if type(n) is not int or not 0<=n<=65535:raise RuntimeError('Invalid FIFO length')
        return n
    try:
        check();cleanup(controller,c)
        # Execute all configured cooling groups and FPGA outer loops in one run.
        # FIFO packets are transport reads, not separate measurement chunks.
        for batch in range(c['outer_loop']):
            check()
            started_at=datetime.now().astimezone().isoformat(timespec='milliseconds')
            batch_clock=time.monotonic();received_rows=0;sequencer_started_at=None;first_fifo_received_at=None;last_fifo_received_at=None
            status='failed';error=''
            if on_batch:on_batch(dict(event='started',batch=batch,status='running',started_at=started_at,
                finished_at=None,programmed_trials=c['run_number']*c['outer_loop_in_fpga']*c['wo_cooling_number']))
            try:
                stale=length()
                while stale:
                    check();size=min(stale,500);d.read_fifo_data(size);stale-=size
                build_program(c).program(show=False,target=d);check();d.auto_mode();d.start_sequencer();sequencer_started_at=datetime.now().astimezone().isoformat(timespec='milliseconds')
                rows=[];deadline=time.monotonic()+c['timeout_s'];start=time.monotonic()
                while True:
                    check()
                    if time.monotonic()>deadline:raise TimeoutError('Decay batch timeout')
                    status=d.sequencer_running_status()
                    if status not in ('running','stopped'):raise RuntimeError('Invalid sequencer status')
                    available=length()
                    while available:
                        check()
                        if time.monotonic()>deadline:raise TimeoutError('Decay FIFO timeout')
                        size=min(available,500);values=d.read_fifo_data(size)
                        last_fifo_received_at=datetime.now().astimezone().isoformat(timespec='milliseconds')
                        if first_fifo_received_at is None:first_fifo_received_at=last_fifo_received_at
                        valid=isinstance(values,list) and len(values)==size and len(rows)+size<=expected and all(isinstance(r,(list,tuple)) and len(r)==4 and all(type(v) is int and 0<=v<=65535 for v in r) and r[3]==100 for r in values)
                        received_rows+=len(values) if isinstance(values,list) else 1
                        on_rows(batch,0,values,valid)
                        if not valid:raise RuntimeError('Invalid decay FIFO payload/tag/length')
                        rows.extend(values);available-=size
                    if status=='stopped':break
                    time.sleep(.001)
                if len(rows)!=expected:raise RuntimeError(f'Missing decay histogram rows: {len(rows)}/{expected}')
                flat=[v for r in rows for v in r[:3]]
                on_chunk(dict(batch=batch,chunk=0,groups=c['run_number']*c['outer_loop_in_fpga'],outer_index=0,trials=c['run_number']*c['outer_loop_in_fpga']*c['wo_cooling_number'],elapsed_s=time.monotonic()-start,
                    batch_complete=True,
                    histograms=[flat[i*bins:(i+1)*bins] for i in range(channels)]))
                status='completed'
            except Exception as exc:
                status='cancelled' if isinstance(exc,OperationCancelled) else 'failed'
                error=f'{type(exc).__name__}: {exc}'
                raise
            finally:
                if on_batch:on_batch(dict(event='finished',batch=batch,status=status,error=error,
                    started_at=started_at,finished_at=datetime.now().astimezone().isoformat(timespec='milliseconds'),
                    sequencer_started_at=sequencer_started_at,first_fifo_received_at=first_fifo_received_at,last_fifo_received_at=last_fifo_received_at,elapsed_s=time.monotonic()-batch_clock,
                    received_fifo_rows=received_rows,expected_fifo_rows=expected,
                    programmed_trials=c['run_number']*c['outer_loop_in_fpga']*c['wo_cooling_number']))
    except Exception as original:
        try:cleanup(controller,c)
        except Exception as exc:raise RuntimeError(f'Decay cleanup failed: {exc}; original: {original}') from exc
        raise
    else:cleanup(controller,c)
