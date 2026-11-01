"""One Rabi pulse-length point on the existing FPGA serial worker."""
import threading
import time
from labremote.characterization.rabi import hardware
from labremote.characterization.rabi_sequence import setup_rabi_program
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram
from labremote.runtime.errors import OperationCancelled

def cleanup(controller,roles):
    d=controller.device
    if d is None:raise RuntimeError('FPGA disconnected; Rabi cleanup not confirmed')
    h=hardware(roles);d.stop_sequencer();s=SequencerProgram()
    s.set_output_port(h.counter_control_port,[(h.PMT_counter_enable,0)])
    s.set_output_port(h.external_control_port,[(h.MW_out,0),(h.EOM_2G_out,0),(h.EOM_7G_1_out,1),(h.EOM_7G_2_out,1),(h.AOM_out,1)])
    s.stop();d.auto_mode();controller._run(s,0,threading.Event())

def acquire(controller,c,index,cancelled,on_rows):
    controller._idle();d=controller.device
    program=setup_rabi_program(index,c,hardware(c['roles']))
    def check():
        if cancelled.is_set():raise OperationCancelled('Rabi cancelled')
    def length():
        n=d.fifo_data_length()
        if type(n) is not int or not 0<=n<=65535:raise RuntimeError('Invalid FIFO length')
        return n
    try:
        check();stale=length()
        while stale:
            check();n=min(stale,500);d.read_fifo_data(n);stale-=n
        program.program(show=False,target=d);check();d.auto_mode();d.start_sequencer()
        deadline=time.monotonic()+c['timeout_s'];counts=[]
        while True:
            check()
            if time.monotonic()>deadline:raise TimeoutError('Rabi point timeout')
            state=d.sequencer_running_status()
            if state not in ('running','stopped'):raise RuntimeError('Invalid sequencer status')
            n=length()
            while n:
                check()
                if time.monotonic()>deadline:raise TimeoutError('Rabi FIFO timeout')
                size=min(n,500);rows=d.read_fifo_data(size)
                if not isinstance(rows,list) or len(rows)!=size or any(len(r)!=4 for r in rows):raise RuntimeError('Malformed Rabi FIFO')
                valid=all(all(type(v) is int and 0<=v<=65535 for v in r) and r[0]==len(counts)+i and r[1]==index and r[3]==10 for i,r in enumerate(rows)) and len(counts)+size<=c['N_average']
                on_rows(rows,valid)
                if not valid:raise RuntimeError('Unexpected Rabi FIFO index/tag')
                counts.extend(r[2] for r in rows);n-=size
            if state=='stopped':break
            time.sleep(.001)
        if len(counts)!=c['N_average']:raise RuntimeError('Missing Rabi samples')
        return counts
    except Exception as original:
        try:cleanup(controller,c['roles'])
        except Exception as exc:raise RuntimeError(f'Rabi FPGA cleanup failed: {exc}; original: {original}') from exc
        raise
