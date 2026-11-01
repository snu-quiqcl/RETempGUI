"""Exclusive decay acquisition with bounded histogram counters and cleanup."""
import threading
import time
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

def run(controller,c,cancelled,on_rows,on_chunk):
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
        # Each PMT can contribute at most once per trial. Never let a 16-bit
        # histogram bin receive more than 65535 events before reading it out.
        max_groups=65535//c['wo_cooling_number']
        for batch in range(c['outer_loop']):
            chunk=0
            for outer in range(c['outer_loop_in_fpga']):
                remaining=c['run_number']
                while remaining:
                    check();groups=min(max_groups,remaining);effective=dict(c,run_number=groups,outer_loop_in_fpga=1)
                    stale=length()
                    while stale:
                        check();size=min(stale,500);d.read_fifo_data(size);stale-=size
                    build_program(effective).program(show=False,target=d);check();d.auto_mode();d.start_sequencer()
                    rows=[];deadline=time.monotonic()+c['timeout_s'];start=time.monotonic()
                    while True:
                        check()
                        if time.monotonic()>deadline:raise TimeoutError('Decay chunk timeout')
                        status=d.sequencer_running_status()
                        if status not in ('running','stopped'):raise RuntimeError('Invalid sequencer status')
                        available=length()
                        while available:
                            check()
                            if time.monotonic()>deadline:raise TimeoutError('Decay FIFO timeout')
                            size=min(available,500);values=d.read_fifo_data(size)
                            valid=isinstance(values,list) and len(values)==size and len(rows)+size<=expected and all(isinstance(r,(list,tuple)) and len(r)==4 and all(type(v) is int and 0<=v<=65535 for v in r) and r[3]==100 for r in values)
                            on_rows(batch,chunk,values,valid)
                            if not valid:raise RuntimeError('Invalid decay FIFO payload/tag/length')
                            rows.extend(values);available-=size
                        if status=='stopped':break
                        time.sleep(.001)
                    if len(rows)!=expected:raise RuntimeError(f'Missing decay histogram rows: {len(rows)}/{expected}')
                    flat=[v for r in rows for v in r[:3]]
                    on_chunk(dict(batch=batch,chunk=chunk,groups=groups,outer_index=outer,trials=groups*c['wo_cooling_number'],elapsed_s=time.monotonic()-start,
                        batch_complete=outer==c['outer_loop_in_fpga']-1 and remaining==groups,
                        histograms=[flat[i*bins:(i+1)*bins] for i in range(channels)]))
                    remaining-=groups;chunk+=1
    except Exception as original:
        try:cleanup(controller,c)
        except Exception as exc:raise RuntimeError(f'Decay cleanup failed: {exc}; original: {original}') from exc
        raise
    else:cleanup(controller,c)
