"""Worker-thread acquisition with FIFO streaming and output cleanup."""
import threading
import time
from labremote.runtime.errors import OperationCancelled
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram
from .config import hd
from .sequence import build_program


def cleanup(controller, c):
    d = controller.device
    d.stop_sequencer()
    if d.sequencer_running_status() != 'stopped':
        raise ConnectionError('Phase Ramsey STOP was not confirmed')
    s = SequencerProgram()
    ports = {}
    for role, state in dict(microwave=0, aom=1, eom_7g_1=1, eom_7g_2=1, eom_2g=0).items():
        name = c['outputs'][role]
        port = hd.external_slow_port if hd.output_mapping[name].startswith(('jc_', 'jd_')) else hd.external_control_port
        ports.setdefault(port, []).append((getattr(hd, name + '_out'), state))
    ports.setdefault(hd.external_slow_port, []).extend(
        (getattr(hd, name + '_out'), 0) for name in c['phase_outputs'])
    for port, bits in ports.items():
        s.set_output_port(port, bits)
    s.set_output_port(hd.counter_control_port,
                      [(getattr(hd, c['detector_nickname'] + '_counter_enable'), 0)])
    s.stop()
    d.auto_mode()
    controller._run(s, 0, threading.Event())


def run(controller, c, scan_codes, cancelled, on_rows, on_point):
    controller._idle()
    d = controller.device

    def check():
        if cancelled.is_set():
            raise OperationCancelled('Phase Ramsey cancelled')

    def length():
        value = d.fifo_data_length()
        if type(value) is not int or not 0 <= value <= 65535:
            raise ValueError('Invalid FIFO length')
        return value

    def read(n):
        rows = d.read_fifo_data(n)
        if not isinstance(rows, list) or len(rows) != n or any(
                not isinstance(r, (list, tuple)) or len(r) != 4 or
                any(type(v) is not int or not 0 <= v <= 65535 for v in r) for r in rows):
            raise ValueError('Invalid FIFO records')
        return rows

    try:
        check()
        for code in scan_codes:
            check()
            program = build_program(dict(c, phase_code=code), hd)
            stale = length()
            while stale:
                check()
                n = min(stale, 512)
                read(n)
                stale -= n
            program.program(show=False, target=d)
            check()
            d.auto_mode()
            d.start_sequencer()
            deadline = time.monotonic() + c['timeout_s']
            count = bright = total = 0
            while True:
                check()
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'Phase code {code}: timeout')
                state = d.sequencer_running_status()
                if state not in ('running', 'stopped'):
                    raise ValueError('Invalid sequencer status')
                available = length()
                while available:
                    check()
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f'Phase code {code}: FIFO timeout')
                    n = min(available, 512)
                    rows = read(n)
                    on_rows(code, rows)  # Preserve even records rejected by validation below.
                    for shot, actual_code, photons, tag in rows:
                        if tag != 5 or actual_code != code or shot != count or count >= c['N_average']:
                            raise ValueError('Phase Ramsey FIFO code, shot order or tag mismatch')
                        count += 1
                        bright += photons >= c['threshold']
                        total += photons
                    available -= n
                if state == 'stopped':
                    break
                time.sleep(.01)
            if count != c['N_average']:
                raise ValueError(f'Incomplete FIFO: {count}/{c["N_average"]} shots')
            on_point(dict(code=code, shots=count, bright=bright,
                          probability=bright/count, mean_count=total/count))
    finally:
        try:
            cleanup(controller, c)
        except Exception as exc:
            raise ConnectionError('Phase Ramsey output cleanup failed: ' + str(exc)) from exc
