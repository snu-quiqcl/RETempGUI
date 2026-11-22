"""Same-phase Hahn echo; tau is total free evolution, excluding pulses."""
from labremote.devices.fpga.vendor.SequencerProgram_v1_09 import SequencerProgram, reg
from .ramsey_sequence import delay_clocks

def build_program(config,hd):
    if not 8 <= config['precession_time'] <= 1_000_000_000 or config['precession_time'] % 2:
        raise ValueError('Precession step must be 0.04 us to 10 s')
    T_cool = config['T_cool']
    T_cool_repeat = config['T_cool_repeat']
    T_init = config['T_init']
    T_det = config['T_det']
    T_det_repeat = config['T_det_repeat']
    T_wait_for_aom_off = config['T_wait_for_aom_off']
    N_average = config['N_average']
    half_pi_time = config['half_pi_time']
    precession_time = config['precession_time']
    max_precession_count = config['max_precession_count']
    Microwave_12_6GHz = hd.MW_out
    EOM_14_7GHz = hd.EOM_7G_1_out
    EOM_2_1GHz = hd.EOM_2G_out
    AOM_on_off = hd.AOM_out
    number_of_runs_R = reg[5]
    count_measured_PMT_R = reg[6]
    count_cooling_R = reg[7]
    count_detection_R = reg[8]
    count_initalization_R = reg[9]
    count_free_precession_R = reg[10]
    control_free_precession_R = reg[11]
    max_count_R = reg[12]
    s = SequencerProgram()
    s.set_output_port(hd.MW_port, [(Microwave_12_6GHz, 0)])
    s.load_immediate(number_of_runs_R, 0, 'number_of_runs_R is the number of runs done')
    s.load_immediate(control_free_precession_R, 0, 'count_initalization_R will be used to count the loop of initialization timer')
    s.repeat_run = s.load_immediate(count_measured_PMT_R, 0, 'count_measured_PMT_R will be used to count the measured result of PMT')
    s.load_immediate(count_cooling_R, 0, 'count_cooling_R will be used to count the loop of cooling timer')
    s.load_immediate(count_detection_R, 0, 'count_detection_R will be used to count the loop of detection timer')
    s.load_immediate(count_initalization_R, 0, 'count_initalization_R will be used to count the loop of initialization timer')
    s.load_immediate(count_free_precession_R, 0, 'count_initalization_R will be used to count the loop of initialization timer')
    s.set_output_port(hd.external_control_port, [(EOM_14_7GHz, 1), (hd.EOM_7G_2_out, 1), (AOM_on_off, 1)], 'Start Cooling')
    s.repeat_cool = s.wait_n_clocks(T_cool, 'Cooling for 50000 * 10 ns = 0.5 ms')
    s.add(count_cooling_R, count_cooling_R, 1, 'count_cooling_R++')
    s.branch_if_less_than('repeat_cool', count_cooling_R, T_cool_repeat, 'Wait for 1ms')
    s.set_output_port(hd.external_control_port, [(EOM_14_7GHz, 0), (hd.EOM_7G_2_out, 0), (EOM_2_1GHz, 1)], 'Start Initialization')
    s.repeat_init = s.wait_n_clocks(T_init, 'Initialization for 50000 * 10 ns = 0.5 ms')
    s.set_output_port(hd.external_control_port, [(AOM_on_off, 0)], 'End Initialization')
    s.wait_n_clocks(T_wait_for_aom_off, 'Wait for the AOM completely off')
    s.set_output_port(hd.external_control_port, [(EOM_2_1GHz, 0)], 'End Initialization')
    s.branch_if_equal('zero_echo', control_free_precession_R, 0)
    s.set_output_port(hd.MW_port, [(Microwave_12_6GHz, 1)])
    delay_clocks(s, half_pi_time-1, 'first_pulse_chunk')
    for side in ('left', 'right'):
        s.set_output_port(hd.MW_port, [(Microwave_12_6GHz, 0)])
        delay_clocks(s, precession_time//2-4, side+'_first_chunk')
        s.add(count_free_precession_R, count_free_precession_R, 1)
        s.branch_if_equal(side+'_pulse', count_free_precession_R, control_free_precession_R)
        setattr(s, side+'_repeat', delay_clocks(s, precession_time//2-3, side+'_repeat_chunk'))
        s.add(count_free_precession_R, count_free_precession_R, 1)
        s.branch_if_less_than(side+'_repeat', count_free_precession_R, control_free_precession_R)
        setattr(s, side+'_pulse', s.set_output_port(hd.MW_port, [(Microwave_12_6GHz, 1)]))
        if side=='left':
            # Reset the next gap counter during the central pi pulse.
            s.load_immediate(count_free_precession_R, 0)
            delay_clocks(s, 2*half_pi_time-2, 'pi_pulse_chunk')
        else:
            delay_clocks(s, half_pi_time-1, 'last_pulse_chunk')
    s.set_output_port(hd.MW_port, [(Microwave_12_6GHz, 0)])
    s.jump('echo_detection')
    # Zero free evolution: contiguous same-phase pi/2 + pi + pi/2 = 2pi.
    s.zero_echo = s.set_output_port(hd.MW_port, [(Microwave_12_6GHz, 1)])
    delay_clocks(s, 4*half_pi_time-1, 'zero_pulse_chunk')
    s.set_output_port(hd.MW_port, [(Microwave_12_6GHz, 0)])
    s.echo_detection = s.set_output_port(hd.external_control_port, [(AOM_on_off, 1)], 'Start Detection')
    s.trigger_out([hd.PMT_counter_reset], 'Reset single counter')
    s.nop()
    s.set_output_port(hd.counter_control_port, [(hd.PMT_counter_enable, 1)], 'Start counter')
    s.repeat_detect = s.wait_n_clocks(T_det, 'Cooling for 50000 * 10 ns = 0.5 ms')
    s.add(count_detection_R, count_detection_R, 1, 'count_detection_R++')
    s.branch_if_less_than('repeat_detect', count_detection_R, T_det_repeat, 'Wait for 1ms')
    s.set_output_port(hd.counter_control_port, [(hd.PMT_counter_enable, 0)], 'Stop counter')
    s.read_counter(count_measured_PMT_R, hd.PMT_counter_result)
    s.write_to_fifo(number_of_runs_R, control_free_precession_R, count_measured_PMT_R, 5, 'Store data')
    s.set_output_port(hd.external_control_port, [(EOM_14_7GHz, 1), (hd.EOM_7G_2_out, 1), (AOM_on_off, 1)], 'Resume Cooling')
    s.add(number_of_runs_R, number_of_runs_R, 1)
    s.branch_if_less_than('repeat_run', number_of_runs_R, N_average, 'Repeat')
    s.load_immediate(number_of_runs_R, 0, 'l')
    s.add(control_free_precession_R, control_free_precession_R, 1, 'reg[6]++')
    s.branch_if_less_than('repeat_run', control_free_precession_R, max_precession_count, 'Repeat, increasing microwave time')
    s.stop()
    return s
