"""One Rabi pulse-length point on the existing FPGA serial worker."""
import threading
import time
from labremote.experiments.characterization.rabi.model import hardware, detector_roles
from labremote.experiments.characterization.rabi.sequence import setup_rabi_program
from labremote.devices.fpga.vendor.SequencerProgram_v1_09 import SequencerProgram
from labremote.runtime.errors import OperationCancelled

def cleanup(controller,roles):
    d=controller.device
    if d is None:raise RuntimeError('FPGA disconnected; Rabi cleanup not confirmed')
    h=hardware(roles);d.stop_sequencer();s=SequencerProgram()
    enables=[h.PMT_counter_enable]+([h.PMT2_counter_enable] if roles.get('PMT2') else [])
    s.set_output_port(h.counter_control_port,[(bit,0) for bit in enables])
    s.set_output_port(h.MW_port,[(h.MW_out,0)])
    s.set_output_port(h.external_control_port,[(h.EOM_2G_out,0),(h.EOM_7G_1_out,1),(h.EOM_7G_2_out,1),(h.AOM_out,1)])
    s.stop();d.auto_mode();controller._run(s,0,threading.Event())

def acquire(controller,c,index,cancelled,on_rows):
    if c.get('detector_count',1)==1:
        return _acquire_batch(controller,c,index,cancelled,on_rows)
    # The FPGA has 1024 16-bit words. Keep the public 1024-shot limit by
    # collecting paired counters in batches of at most 512 shots.
    counts={role:[] for role in detector_roles(c)}
    deadline=time.monotonic()+c['timeout_s']
    for offset in range(0,c['N_average'],512):
        batch=dict(c,N_average=min(512,c['N_average']-offset))
        def rows(values,valid):
            on_rows([[row[0]+offset if type(row[0]) is int else row[0],*row[1:]] for row in values],valid)
        received=_acquire_batch(controller,batch,index,cancelled,rows,deadline)
        for role in counts:counts[role].extend(received[role])
    return counts


def _acquire_batch(controller,c,index,cancelled,on_rows,deadline=None):
    controller._idle();d=controller.device
    program=setup_rabi_program(index,c,hardware(c['roles']))
    def check():
        if cancelled.is_set():raise OperationCancelled('Rabi cancelled')
        if deadline is not None and time.monotonic()>deadline:raise TimeoutError('Rabi point timeout')
    def length():
        n=d.fifo_data_length()
        if type(n) is not int or not 0<=n<=65535:raise RuntimeError('Invalid FIFO length')
        return n
    check();stale=length()
    while stale:
        check();n=min(stale,500);d.read_fifo_data(n);stale-=n
    program.program(show=False,target=d);check();d.auto_mode();d.start_sequencer()
    if deadline is None:deadline=time.monotonic()+c['timeout_s']
    dual=c.get('detector_count',1)==2;counts=[];second=[]
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
            valid=all(all(type(v) is int and 0<=v<=65535 for v in r) and r[0]==len(counts)+i and ((r[3]==11) if dual else (r[1]==index and r[3]==10)) for i,r in enumerate(rows)) and len(counts)+size<=c['N_average']
            on_rows(rows,valid)
            if not valid:raise RuntimeError('Unexpected Rabi FIFO index/tag')
            counts.extend(r[1] if dual else r[2] for r in rows)
            if dual:second.extend(r[2] for r in rows)
            n-=size
        if state=='stopped':break
        time.sleep(.001)
    if len(counts)!=c['N_average']:raise RuntimeError('Missing Rabi samples')
    return {'PMT':counts,'PMT2':second} if dual else counts

def run(controller,c,cancelled,on_rows,on_point):
    controller._idle()
    try:
        if cancelled.is_set():raise OperationCancelled('Rabi cancelled')
        cleanup(controller,c['roles'])
        for index in range(c['N_qubit_control']):
            counts=acquire(controller,c,index,cancelled,lambda rows,valid:on_rows(index,rows,valid))
            on_point(index,counts)
    except Exception as original:
        try:cleanup(controller,c['roles'])
        except Exception as exc:raise ConnectionError(f'Rabi FPGA cleanup failed: {exc}; original: {original}') from exc
        raise
    else:
        try:cleanup(controller,c['roles'])
        except Exception as exc:raise ConnectionError(f'Rabi FPGA cleanup failed: {exc}') from exc
