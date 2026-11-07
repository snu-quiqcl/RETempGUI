import threading
import time
from datetime import datetime
from labremote.devices.fpga.controller import hd,OUTPUTS
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram
from labremote.runtime.errors import OperationCancelled
from .config import classify,pmt_names,output_levels,defaults

LEVELS=output_levels(defaults())  # Legacy default only; execution uses selected mapping.

class CleanupError(ConnectionError):pass

def cleanup(controller,c=None):
    c=c or defaults()
    if controller.device is None:raise CleanupError('FPGA disconnected; outputs unconfirmed')
    controller.device.stop_sequencer()
    s=SequencerProgram();ports={}
    s.set_output_port(hd.counter_control_port,[(getattr(hd,name+'_counter_enable'),0) for name in pmt_names(c)])
    for name,value in output_levels(c).items():
        _,port,bit=OUTPUTS[name];ports.setdefault(port,[]).append((bit,value))
    for port,values in sorted(ports.items()):s.set_output_port(port,values)
    s.stop();controller.device.auto_mode();controller._run(s,0,threading.Event())

def decode(result):
    rows=result.get('rows') if isinstance(result,dict) else None
    if (not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],(tuple,list))
            or len(rows[0])!=4 or result.get('stopped') is not True
            or any(type(v) is not int or not 0<=v<=65535 for v in rows[0])):
        raise ValueError('Invalid Ion Check FIFO result')
    if rows[0][3]==0x11:raise OverflowError('PMT sum overflow; reduce exposure time')
    if rows[0][3]!=0x10:raise ValueError('Unknown Ion Check FIFO tag')
    return rows[0][:3]

def run(controller,c,mode,sequence_path,cancelled,on_sample,on_cleanup):
    def check():
        if cancelled.is_set():raise OperationCancelled('Ion Check cancelled')
    check();controller._idle()
    try:
        for attempt in range(1,(1 if mode=='once' else c['max_attempts'])+1):
            check();controller.device.auto_mode()
            result=controller.run_sequence_file(dict(path=str(sequence_path),
                parameters=dict(exposure_us=c['exposure_us'],settle_us=c['settle_us'],mapping=c.get('mapping',defaults()['mapping'])),
                timeout_s=c['timeout_s'],max_rows=1),cancelled)
            check();counts=decode(result);decision,bright=classify(counts,c)
            sample=dict(attempt=attempt,measured_at=datetime.now().astimezone().isoformat(timespec='milliseconds'),
                        counts=dict(zip('abc',counts)),bright=bright,decision=decision,
                        dac='not_implemented',rows=result['rows'],sequence_sha256=result.get('sha256'))
            on_sample(sample)
            if mode=='once' or decision=='normal':return decision
            if attempt<c['max_attempts']:
                deadline=time.monotonic()+c['retry_delay_s']
                while time.monotonic()<deadline:
                    check();time.sleep(min(.02,max(0,deadline-time.monotonic())))
        return decision
    finally:
        try:cleanup(controller,c)
        except Exception as exc:
            on_cleanup('failed');raise CleanupError('Ion Check output cleanup failed: '+str(exc)) from exc
        on_cleanup('completed')
