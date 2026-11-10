"""12-bit phase Ramsey; one code / N_average shots per FPGA program.

build_program(parameters, hd=None) also supports the existing sequence-file loader.
All timing values are FPGA clocks (10 ns on the current sequencer).
phase_outputs contains hardware-definition nicknames in D0 (LSB) .. D11 order.
No physical pin assignment is made here. No hardware is contacted by this file.
"""
from importlib import import_module

from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram, reg


def build_program(parameters, hd=None):
    p = parameters
    if hd is None:
        hd = import_module(p['hardware_definition_module'])

    def integer(key, low, high):
        value = p[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key} must be an integer in [{low}, {high}]')
        return value

    def output(nickname):
        if not isinstance(nickname, str) or nickname not in hd.output_mapping:
            raise ValueError(f'Unknown hardware-definition output nickname: {nickname!r}')
        pin = hd.output_mapping[nickname]
        port = (hd.external_slow_port if pin.startswith(('jc_', 'jd_'))
                else hd.external_control_port)
        bit = getattr(hd, nickname + '_out')
        if type(bit) is not int or not 0 <= bit <= 15:
            raise ValueError(f'Invalid output bit for {nickname}')
        return port, bit

    names = p['phase_outputs']
    if not isinstance(names, (list, tuple)) or len(names) != 12:
        raise ValueError('phase_outputs requires 12 nicknames ordered D0 .. D11')
    phase = [output(name) for name in names]
    if len(set(phase)) != 12 or any(port != hd.external_slow_port for port, _ in phase):
        raise ValueError('Phase outputs must resolve to 12 distinct slow output bits')
    outputs = {role: output(p['outputs'][role])
               for role in ('microwave', 'aom', 'eom_7g_1', 'eom_7g_2', 'eom_2g')}
    if len(set(outputs.values())) != len(outputs) or set(phase) & set(outputs.values()):
        raise ValueError('Experiment outputs and phase bits must not overlap')
    if outputs['microwave'][0] != hd.external_control_port:
        raise ValueError('Microwave pulse gate requires a fast output')

    code = integer('phase_code', 0, 4095)
    averages = integer('N_average', 1, 65535)
    half_pi = integer('half_pi_time', 3, 65538)
    zero_settle = integer('phase_zero_settle_clocks', 3, 65538)
    phase_settle = integer('phase_settle_clocks', 3, 65538)
    cool = integer('T_cool', 0, 65535)
    cool_repeat = integer('T_cool_repeat', 1, 65535)
    init = integer('T_init', 0, 65535)
    det = integer('T_det', 0, 65535)
    det_repeat = integer('T_det_repeat', 1, 65535)
    aom_off = integer('T_wait_for_aom_off', 0, 65535)
    detector = p['detector_nickname']
    if detector not in hd.input_mapping.values():
        raise ValueError(f'Unknown detector nickname: {detector!r}')
    counter_enable = getattr(hd, detector + '_counter_enable')
    counter_reset = getattr(hd, detector + '_counter_reset')
    counter_result = getattr(hd, detector + '_counter_result')

    s = SequencerProgram()
    shot, counts, cooling, detection, phase_code = (
        reg[5], reg[6], reg[7], reg[8], reg[9])

    def set_outputs(comment, **states):
        ports = {}
        for role, state in states.items():
            port, bit = outputs[role]
            ports.setdefault(port, []).append((bit, state))
        for port, bits in ports.items():
            s.set_output_port(port, bits, comment)

    def set_phase(value, comment):
        # One masked write updates all 12 bits, including zeros, simultaneously.
        # The other four slow outputs are preserved.
        return s.set_output_port(hd.external_slow_port,
                                 [(bit, (value >> i) & 1)
                                  for i, (_, bit) in enumerate(phase)], comment)

    set_outputs('Microwave OFF before sequence', microwave=0)
    s.set_output_port(hd.counter_control_port, [(counter_enable, 0)])
    set_phase(0, 'Initial phase reset')
    s.load_immediate(shot, 0)
    s.load_immediate(phase_code, code)
    s.repeat_run = s.load_immediate(cooling, 0)
    s.load_immediate(detection, 0)
    set_outputs('Cooling', eom_7g_1=1, eom_7g_2=1, eom_2g=0, aom=1)
    s.repeat_cool = s.wait_n_clocks(cool)
    s.add(cooling, cooling, 1)
    s.branch_if_less_than('repeat_cool', cooling, cool_repeat)
    set_outputs('Initialize ion', eom_7g_1=0, eom_7g_2=0, eom_2g=1)
    s.wait_n_clocks(init)
    set_outputs('AOM OFF', aom=0)
    s.wait_n_clocks(aom_off)
    set_outputs('Initialization complete', eom_2g=0)

    # This reset is INSIDE repeat_run: every first pi/2 has a zero-code reference.
    set_phase(0, 'Force all 12 phase bits LOW before first pi/2')
    s.wait_n_clocks(zero_settle - 3, 'Zero-code settling')
    set_outputs('First pi/2 ON', microwave=1)
    # wait(n) consumes n+2 clocks; the output instruction consumes one clock.
    s.wait_n_clocks(half_pi - 3)
    set_outputs('First pi/2 OFF', microwave=0)
    set_phase(code, 'Target phase code while microwave is OFF')
    s.wait_n_clocks(phase_settle - 3, 'Fixed phase settling')
    set_outputs('Second pi/2 ON', microwave=1)
    s.wait_n_clocks(half_pi - 3)
    set_outputs('Second pi/2 OFF', microwave=0)

    set_outputs('Detection', aom=1)
    s.trigger_out([counter_reset])
    s.nop()
    s.set_output_port(hd.counter_control_port, [(counter_enable, 1)])
    s.repeat_detect = s.wait_n_clocks(det)
    s.add(detection, detection, 1)
    s.branch_if_less_than('repeat_detect', detection, det_repeat)
    s.set_output_port(hd.counter_control_port, [(counter_enable, 0)])
    s.read_counter(counts, counter_result)
    s.write_to_fifo(shot, phase_code, counts, 5, 'shot index, phase code, PMT count')
    set_phase(0, 'Restore zero phase after detection')
    set_outputs('Resume cooling', eom_7g_1=1, eom_7g_2=1, eom_2g=0, aom=1)
    s.add(shot, shot, 1)
    s.branch_if_less_than('repeat_run', shot, averages)
    s.stop()
    return s
