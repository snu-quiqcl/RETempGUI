"""Local serial controller. All methods are called by one worker thread."""
import time
from contextlib import contextmanager


@contextmanager
def timed_stage(timings, name):
    start = time.perf_counter()
    try:
        yield
    finally:
        if timings is not None:
            timings[name] = (time.perf_counter() - start) * 1000

from labremote.devices.fpga.vendor import HardwareDefinition_remote_ent_test_ec as hd
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram, reg

OUTPUTS = {
    name: (pin, hd.external_slow_port if pin.startswith(('jc_', 'jd_'))
           else hd.external_control_port, getattr(hd, name + '_out'))
    for name, pin in hd.output_mapping.items()
}
INPUTS = {
    getattr(hd, name + '_counter_result'): (name, pin)
    for pin, name in hd.input_mapping.items()
    if hasattr(hd, name + '_counter_result')
}


def exposure_program(channel, milliseconds):
    if channel not in INPUTS or not 0.1 <= milliseconds <= 6000:
        raise ValueError('PMT 번호 또는 노출 시간 범위 오류')
    ticks = round(milliseconds * 10)
    name = INPUTS[channel][0]
    s = SequencerProgram()
    s.load_immediate(reg[0], channel)
    s.load_immediate(reg[1], 0)
    s.trigger_out([getattr(hd, name + '_counter_reset')])
    s.set_output_port(hd.counter_control_port, [(getattr(hd, name + '_counter_enable'), 1)])
    # Same timing as simple_exposure: wait (9995+2), add (1), branch (2).
    s.exposure_loop = s.wait_n_clocks(9995)
    s.add(reg[1], reg[1], 1)
    s.branch_if_less_than('exposure_loop', reg[1], ticks)
    s.set_output_port(hd.counter_control_port, [(getattr(hd, name + '_counter_enable'), 0)])
    s.read_counter(reg[2], channel)
    s.write_to_fifo(reg[0], reg[1], reg[2], 10)
    s.stop()
    return s, ticks / 10


class Controller:
    def __init__(self, factory=None):
        self.device = None
        self.factory = factory
        self.last_measurement_timings = {}

    def connect(self, port):
        if not port.strip():
            raise ValueError('COM 포트를 입력하세요.')
        if self.device is not None:
            raise RuntimeError('이미 연결되어 있습니다.')
        if self.factory is None:
            from labremote.devices.fpga.vendor.ArtyS7_v1_02 import ArtyS7
            factory = ArtyS7
        else:
            factory = self.factory
        device = factory(port.strip())
        try:
            device.com.write_timeout = 2
            device.check_version(hd.HW_VERSION)
            if device.sequencer_running_status() != 'stopped':
                raise RuntimeError('다른 시퀀스가 실행 중입니다. 먼저 종료하세요.')
        except Exception:
            device.close()
            raise
        self.device = device
        return self.states()

    def disconnect(self):
        device, self.device = self.device, None
        if device is not None:
            device.close()

    def states(self):
        reply = self.device.escape_read()
        if reply[0] != '\x10R' or len(reply[2]) != 4:
            raise RuntimeError('FPGA 상태 응답 오류')
        word = int(''.join(reply[2][:2]), 2)
        return {name: bool(word & (1 << bit)) if port == 0 else None
                for name, (_, port, bit) in OUTPUTS.items()}

    def _idle(self):
        if self.device is None:
            raise RuntimeError('FPGA를 먼저 연결하세요.')
        if self.device.sequencer_running_status() != 'stopped':
            raise RuntimeError('다른 시퀀스가 실행 중입니다.')

    def _run(self, program, seconds, cancelled, timings=None):
        with timed_stage(timings, 'program_upload'):
            program.program(show=False, target=self.device)
        with timed_stage(timings, 'start'):
            self.device.start_sequencer()
        with timed_stage(timings, 'completion_wait'):
            deadline = time.monotonic() + seconds + 3
            while True:
                if cancelled.is_set():
                    raise InterruptedError('측정 취소')
                status = self.device.sequencer_running_status()
                if status == 'stopped':
                    return
                if status != 'running':
                    raise RuntimeError('FPGA 실행 상태 응답 오류')
                if time.monotonic() > deadline:
                    raise TimeoutError('FPGA 응답 시간 초과')
                time.sleep(0.01)

    def set_output(self, name, enabled, cancelled):
        self._idle()
        _, port, bit = OUTPUTS[name]
        s = SequencerProgram()
        # Preserve current external outputs even when taking over manual mode.
        states = self.states()
        s.set_output_port(hd.external_control_port,
                          [(OUTPUTS[n][2], int(v)) for n, v in states.items() if v is not None])
        s.set_output_port(port, [(bit, int(enabled))])
        s.stop()
        self._run(s, 0, cancelled)
        self.device.auto_mode()
        states = self.states()
        if port == 0 and states[name] != bool(enabled):
            raise RuntimeError('출력 상태 확인 실패')
        states[name] = bool(enabled)
        return states

    def measure(self, channel, milliseconds, cancelled):
        timings = {'error_cleanup': 0.0}
        self.last_measurement_timings = timings
        with timed_stage(timings, 'total'):
            with timed_stage(timings, 'idle_check'):
                self._idle()
            with timed_stage(timings, 'program_build'):
                program, actual_ms = exposure_program(channel, milliseconds)
            # Bounded flush: stopped sequencer cannot produce additional records.
            with timed_stage(timings, 'fifo_flush'):
                length = self.device.fifo_data_length()
                if not isinstance(length, int) or not 0 <= length <= 65535:
                    raise RuntimeError('FIFO 길이 응답 오류')
                while length:
                    chunk = min(length, 512)
                    rows = self.device.read_fifo_data(chunk)
                    if rows is None or len(rows) != chunk:
                        raise RuntimeError('FIFO 정리 실패')
                    length -= chunk
            try:
                self._run(program, actual_ms / 1000, cancelled, timings)
                with timed_stage(timings, 'fifo_read'):
                    if self.device.fifo_data_length() != 1:
                        raise RuntimeError('측정 결과 FIFO 레코드 수 오류')
                    rows = self.device.read_fifo_data(1)
                    if not rows or len(rows[0]) != 4 or rows[0][:2] != [channel, round(actual_ms * 10)] or rows[0][3] != 10:
                        raise RuntimeError('측정 결과 FIFO 형식 오류')
            except Exception as error:
                # Interrupted programs may leave the counter enabled. Successful
                # programs already disable it and STOP before producing a result.
                try:
                    with timed_stage(timings, 'error_cleanup'):
                        self.device.stop_sequencer()
                        cleanup = SequencerProgram()
                        cleanup.set_output_port(hd.counter_control_port,
                            [(getattr(hd, INPUTS[channel][0] + '_counter_enable'), 0)])
                        cleanup.stop()
                        import threading
                        self._run(cleanup, 0, threading.Event())
                except Exception as cleanup_error:
                    # A cleanup/transport failure must remain visible to the worker.
                    raise cleanup_error from error
                raise
        return {'channel': channel, 'ms': actual_ms, 'count': rows[0][2],
                'timings_ms': dict(timings)}
