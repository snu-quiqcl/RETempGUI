"""Exclusive acquisition, strict FIFO protocol and unconditional output cleanup."""
import threading
import time
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


def run(controller, c, cancelled, on_rows, on_batch, on_cleanup=lambda status: None):
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
        for batch in range(c['outer_loop']*c['outer_outer_loop']):
            check()
            stale=length()
            while stale:
                check(); size=min(stale,500); d.read_fifo_data(size); stale-=size
            build_program(c).program(show=False,target=d)
            check(); d.auto_mode(); d.start_sequencer()
            rows=[]; start=time.monotonic(); deadline=start+c['timeout_s']
            while True:
                check()
                if time.monotonic()>deadline:raise TimeoutError('HOM batch timeout')
                status=d.sequencer_running_status()
                if status not in ('running','stopped'):raise ValueError('Invalid sequencer status')
                available=length()
                while available:
                    check()
                    if time.monotonic()>deadline:raise TimeoutError('HOM FIFO timeout')
                    size=min(available,500); values=d.read_fifo_data(size)
                    good=isinstance(values,list) and len(values)==size and len(rows)+size<=expected and all(isinstance(r,(list,tuple)) and len(r)==4 and all(type(v) is int and 0<=v<=65535 for v in r) for r in values)
                    on_rows(batch,values,good)
                    if not good:raise ValueError('Invalid HOM FIFO payload')
                    rows.extend([list(r) for r in values]); available-=size
                if status=='stopped':break
                time.sleep(.001)
            data=decode(rows,c)
            on_batch(dict(data,batch=batch,block=batch//c['outer_loop'],elapsed_s=time.monotonic()-start))
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
