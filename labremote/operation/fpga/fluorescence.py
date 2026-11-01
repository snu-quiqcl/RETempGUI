"""Runs only inside the existing FPGA operation FIFO; no new connection."""
import time
import threading
from labremote.devices.fpga.controller import hd
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram
from labremote.runtime.errors import OperationCancelled


def acquire(controller,settings,route,cancelled,on_rows,on_batch):
    from labremote.characterization.fluorescence import build_program
    device=controller.device;controller._idle()
    program=build_program(settings,route)
    def check():
        if cancelled.is_set():raise OperationCancelled('Fluorescence cancelled')
    def length():
        value=device.fifo_data_length()
        if type(value) is not int or not 0<=value<=65535:raise RuntimeError('Invalid FIFO length')
        return value
    def read(n):
        rows=device.read_fifo_data(n)
        if not isinstance(rows,list) or len(rows)!=n or any(len(row)!=4 for row in rows):raise RuntimeError('Invalid FIFO rows')
        return rows
    try:
        check();stale=length()
        while stale:
            check();n=min(500,stale);read(n);stale-=n
        program.program(show=False,target=device)
        for batch in range(settings['num_repeat']):
            check();device.auto_mode();device.start_sequencer()
            deadline=time.monotonic()+settings['timeout_s'];received=0
            while True:
                check()
                if time.monotonic()>deadline:raise TimeoutError('Fluorescence batch timeout')
                state=device.sequencer_running_status()
                if state not in ('running','stopped'):raise RuntimeError('Invalid sequencer status')
                available=length()
                while available:
                    check()
                    if time.monotonic()>deadline:raise TimeoutError('Fluorescence FIFO timeout')
                    n=min(500,available);rows=read(n)
                    valid=all(all(type(v) is int and 0<=v<=65535 for v in row) and
                              row[0]==received+i and row[1]==round(settings['exposure_ms']*10) and row[3]==10
                              for i,row in enumerate(rows)) and received+n<=settings['num_average']
                    on_rows(batch,rows,valid)  # Persist even malformed rows for diagnosis.
                    if not valid:raise RuntimeError('Unexpected fluorescence FIFO indices/timing/tag')
                    received+=n;available-=n
                if state=='stopped':break
                time.sleep(.001)
            if received!=settings['num_average']:raise RuntimeError(f'Missing samples: batch {batch+1}: {received}/{settings["num_average"]}')
            on_batch(batch+1)
    except Exception as original:
        try:
            device.stop_sequencer()
            cleanup=SequencerProgram()
            cleanup.set_output_port(hd.counter_control_port,[(getattr(hd,route['PMT']+'_counter_enable'),0)])
            cleanup.stop();controller._run(cleanup,0,threading.Event())
        except Exception as error:raise RuntimeError(f'Fluorescence cleanup not confirmed: {error}; original: {original}') from error
        raise
