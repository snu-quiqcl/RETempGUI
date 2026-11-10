"""Set a persistent slow-port phase word through the existing FPGA queue."""
from labremote.api.devices import DeviceAPI
from labremote.devices.fpga.adapter import Cancellation
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram
from labremote.runtime.errors import OperationCancelled
from labremote.runtime.workflow_runner import _TASK_LOCK
from . import config


def request(angle, names, hd=None, calibration=None):
    hd = config.hd if hd is None else hd
    point = config.resolve(angle, calibration)
    if not isinstance(names, (list, tuple)) or len(names) != 12:
        raise ValueError('D0~D11의 nickname 12개를 선택하세요.')
    bits = []
    for name in names:
        if not isinstance(name, str) or name not in hd.output_mapping:
            raise ValueError('D0~D11의 nickname을 모두 선택하세요.')
        pin = hd.output_mapping[name]
        if not pin.startswith(('jc_', 'jd_')):
            raise ValueError(f'{name}: slow output만 선택할 수 있습니다.')
        bit = getattr(hd, name + '_out', None)
        if type(bit) is not int or not 0 <= bit <= 15:
            raise ValueError(f'{name}: 잘못된 출력 비트입니다.')
        bits.append(bit)
    if len(set(bits)) != 12:
        raise ValueError('서로 다른 slow output 12개를 선택하세요. 중복 핀은 사용할 수 없습니다.')
    return dict(point, phase_outputs=list(names), bits=bits, port=hd.external_slow_port)


def program(value):
    s = SequencerProgram()
    s.set_output_port(value['port'], [(bit, (value['code'] >> i) & 1)
                      for i, bit in enumerate(value['bits'])], 'Apply and HOLD phase word')
    s.stop('Keep output latched; no automatic zero reset')
    return s


def apply(controller, value, cancelled):
    if cancelled.is_set():
        raise OperationCancelled('위상 적용 취소')
    controller._idle()
    try:
        # Slow outputs are wired directly to port 2. Do not change the fast-port
        # manual/auto mux, MW gates, counter controls or unrelated slow bits.
        controller._run(program(value), 0, cancelled)
    except Exception:
        # Stop a potentially started program, but never silently overwrite phase
        # with zero. A transport failure leaves output state explicitly unknown.
        controller.device.stop_sequencer()
        if controller.device.sequencer_running_status() != 'stopped':
            raise ConnectionError('위상 적용 오류: sequencer STOP 확인 실패')
        raise
    return dict(value)


def busy(worker):
    return worker.waveform_runner.running() or any(t.running() for t in worker._background_tasks)


def submit(worker, angle, names, calibration=None):
    value = request(angle, names, calibration=calibration)
    with _TASK_LOCK:
        if worker.ps is None or worker.connection_error or worker._closing:
            raise ConnectionError('FPGA를 먼저 연결하세요.')
        if busy(worker) or worker.has_requests():
            raise RuntimeError('다른 FPGA 작업이 끝난 뒤 위상을 적용하세요.')

        def execute(w):
            # Recheck after queueing; another workflow may have started meanwhile.
            if busy(w):
                raise RuntimeError('실험 실행 중에는 수동 위상을 변경할 수 없습니다.')
            return apply(w.raw_device.controller, value, Cancellation())

        return DeviceAPI(worker)._submit('PHASE_HOLD', execute, arguments=value)
