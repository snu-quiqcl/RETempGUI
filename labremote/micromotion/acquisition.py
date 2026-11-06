"""Runs on the existing FPGA worker. Finite polling, cancellation and FIFO validation."""
import time
import threading
import numpy as np
from labremote.runtime.errors import OperationCancelled
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram
from . import config, sequence


class AcquisitionDeadline(RuntimeError):
    """Experiment timeout after cleanup, distinct from a serial transport timeout."""


def execute(controller, c, cancelled, mode='correlation', target=1, on_rows=lambda rows:None):
    controller._idle();device=controller.device
    expected=c['rf_repeats'] if mode=='input' else config.bins(c)//3+1
    program=sequence.rf_test(c) if mode=='input' else sequence.correlation(c,target)
    deadline=time.monotonic()+c['timeout_s']
    def check():
        if cancelled.is_set():raise OperationCancelled('Micromotion acquisition stopped')
        if time.monotonic()>deadline:raise AcquisitionDeadline('No complete measurement before point timeout')
    def length():
        n=device.fifo_data_length()
        if type(n) is not int or not 0<=n<=65535:raise ValueError('Invalid FPGA FIFO length')
        return n
    try:
        check()
        stale=length()
        while stale:
            check();n=min(stale,256);device.read_fifo_data(n);stale-=n
        program.program(show=False,target=device)
        check()
        # Do not switch manual/auto mode or touch fast/slow external output ports.
        device.start_sequencer()
        rows=[]
        while True:
            check();status=device.sequencer_running_status()
            if status not in ('running','stopped'):raise ValueError('Invalid FPGA sequencer status')
            available=length()
            while available:
                check();n=min(available,256);part=device.read_fifo_data(n)
                on_rows(part)
                if not isinstance(part,list) or len(part)!=n or any(
                    not isinstance(row,(list,tuple)) or len(row)!=4 or
                    any(type(v) is not int or not 0<=v<=65535 for v in row) for row in part):
                    raise ValueError('Malformed micromotion FIFO packet')
                rows.extend(part);available-=n
                if len(rows)>expected:raise ValueError('Unexpected extra FIFO records')
            if status=='stopped':break
            time.sleep(.01)
        if len(rows)!=expected:raise ValueError('Incomplete micromotion FIFO records')
        if mode=='input':
            if any(r[0]!=i or r[1]!=r[2] or r[3]!=10 for i,r in enumerate(rows)):
                raise ValueError('RF count packet index/tag mismatch')
            counts=[r[1] for r in rows]
            if max(counts)>=65000:raise OverflowError('RF counter near saturation; shorten gate')
            return dict(counts=counts, expected=c['rf_mhz']*round(c['gate_us']*100)/100,
                        mean=float(np.mean(counts)),std=float(np.std(counts)),
                        gate_us=round(c['gate_us']*100)/100)
        if any(r[3]!=100 for r in rows[:-1]) or rows[-1][3]!=101:
            raise ValueError('Correlation FIFO tag mismatch')
        histogram=[v for r in rows[:-1] for v in r[:3]]
        accepted,lo,hi,_=rows[-1];attempts=lo+65536*hi
        if sum(histogram)!=accepted or accepted>target or attempts<accepted or hi>100:
            raise ValueError('Correlation event accounting mismatch')
        if max(histogram)>30000:raise OverflowError('Histogram overflow')
        return dict(histogram=histogram,accepted=accepted,attempts=attempts)
    finally:
        # Even interruption in an RF gate must disable the INTERNAL counter.
        device.stop_sequencer()
        if mode=='input':
            name=config.PINS[c['counter_pin']];cleanup=SequencerProgram()
            cleanup.set_output_port(config.hd.counter_control_port,
                [(getattr(config.hd,name+'_counter_enable'),0)])
            cleanup.stop();controller._run(cleanup,0,threading.Event())
