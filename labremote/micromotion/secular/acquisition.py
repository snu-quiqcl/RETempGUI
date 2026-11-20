"""Finite FPGA blocks with raw FIFO capture and internal counter cleanup only."""
import math
import threading
import time
from labremote.runtime.errors import OperationCancelled
from labremote.devices.fpga.vendor.SequencerProgram_v1_09 import SequencerProgram
from labremote.micromotion.acquisition import AcquisitionDeadline
from . import config, sequence, model


def execute(controller,c,frequency_khz,cancelled,mode='correlation',attempts=1,target=1,
            timeout_s=None,on_rows=lambda rows:None):
    hardware=config.hardware(c)
    params={'phase_bins':c['phase_bins'],'count_rate_exposure_time_us':c['count_exposure_us']}
    if mode not in ('count','correlation'):raise ValueError('Unknown acquisition mode')
    count=mode=='count'
    program=(sequence._build_count(params,hardware) if count else
             sequence._build_correlation(params,hardware,frequency_khz,attempts,target))
    if len(program.program_list)>512:raise ValueError('FPGA program exceeds 512 instructions')
    expected=math.ceil(c['count_exposure_us']/100) if count else math.ceil(c['phase_bins']/3)+1
    controller._idle();device=controller.device
    deadline=time.monotonic()+(c['point_timeout_s'] if timeout_s is None else timeout_s)
    def check():
        if cancelled.is_set():raise OperationCancelled('Secular scan stopped')
        if time.monotonic()>=deadline:raise AcquisitionDeadline('Secular point timeout')
    def length():
        n=device.fifo_data_length()
        if type(n) is not int or not 0<=n<=65535:raise ValueError('Invalid FPGA FIFO length')
        return n
    try:
        check();stale=length()
        while stale:
            check();n=min(stale,256);part=device.read_fifo_data(n)
            if not isinstance(part,list) or len(part)!=n:raise ValueError('Incomplete stale FIFO flush')
            stale-=n
        program.program(show=False,target=device)
        check();device.start_sequencer();rows=[]
        while True:
            check();status=device.sequencer_running_status()
            if status not in ('running','stopped'):raise ValueError('Invalid FPGA run status')
            available=length()
            while available:
                check();n=min(available,256);part=device.read_fifo_data(n);on_rows(part)
                if not isinstance(part,list) or len(part)!=n or any(
                    not isinstance(r,(list,tuple)) or len(r)!=4 or
                    any(type(v) is not int or not 0<=v<=65535 for v in r) for r in part):
                    raise ValueError('Malformed secular FIFO packet')
                rows.extend(part);available-=n
                if len(rows)>expected:raise ValueError('Extra secular FIFO records')
            if status=='stopped':break
            time.sleep(.01)
        if len(rows)!=expected:raise ValueError('Incomplete secular FIFO records')
        if count:
            segments=model._decode_count(rows,c['count_exposure_us'])
            return dict(count=int(segments[:,0].sum()),exposure_us=float(segments[:,1].sum())/100,
                        segments=segments.tolist())
        hist,actual_attempts,events=model._decode_correlation(rows,c['phase_bins'],attempts,target)
        return dict(histogram=hist.tolist(),attempts=actual_attempts,events=events)
    finally:
        try:device.stop_sequencer()
        finally:
            if count:
                cleanup=SequencerProgram();counter=hardware['pmts'][0]['count']
                cleanup.set_output_port(counter['control_port'],[(counter['enable'],0)]);cleanup.stop()
                try:controller._run(cleanup,0,threading.Event())
                finally:device.stop_sequencer()
