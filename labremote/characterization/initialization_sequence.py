"""Original initialization sweep; uses the active FPGA hardware mapping."""
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram, reg

def build_program(config, hd):
    """Build the initialization-time sweep sequencer program."""
    T_cool = config['T_cool']
    T_cool_repeat = config['T_cool_repeat']
    T_init_step = config['T_init_step']
    T_det = config['T_det']
    T_det_repeat = config['T_det_repeat']
    WAIT_AOM = config['WAIT_AOM']
    N_average = config['N_average']
    N_init_control = config['N_init_control']
    EOM_14G_1 = hd.EOM_7G_1_out
    EOM_14G_2 = hd.EOM_7G_2_out
    EOM_2G = hd.EOM_2G_out
    AOM = hd.AOM_out
    init_time_index_R = reg[6]
    measured_PMT_R = reg[7]
    cooling_counter_R = reg[9]
    detection_counter_R = reg[11]
    run_counter_R = reg[12]
    initialization_counter_R = reg[13]
    s = SequencerProgram()
    s.load_immediate(init_time_index_R, 0, 'initialization-time index')
    s.load_immediate(run_counter_R, 0, 'number of completed trials')
    s.repeat_run = s.load_immediate(measured_PMT_R, 0)
    s.load_immediate(cooling_counter_R, 0)
    s.load_immediate(detection_counter_R, 0)
    s.load_immediate(initialization_counter_R, 0)
    s.set_output_port(hd.external_control_port, [(EOM_14G_1, 1), (EOM_14G_2, 1), (AOM, 1)], 'Start Cooling')
    s.repeat_cool = s.wait_n_clocks(T_cool, 'Cooling')
    s.add(cooling_counter_R, cooling_counter_R, 1)
    s.branch_if_less_than('repeat_cool', cooling_counter_R, T_cool_repeat, 'Repeat cooling')
    s.set_output_port(hd.external_control_port, [(EOM_14G_1, 0), (EOM_14G_2, 0)], 'End Cooling')
    s.wait_n_clocks(WAIT_AOM, 'Wait for AOM off')
    s.branch_if_equal('no_init_time', init_time_index_R, 0, 'No initialization')
    s.set_output_port(hd.external_control_port, [(AOM, 1), (EOM_2G, 1)], 'Start Initialization')
    s.repeat_init = s.wait_n_clocks(T_init_step - 2, 'Initialization step')
    s.add(initialization_counter_R, initialization_counter_R, 1)
    s.branch_if_less_than('repeat_init', initialization_counter_R, init_time_index_R, 'Repeat initialization step')
    s.set_output_port(hd.external_control_port, [(AOM, 0)], 'End Initialization')
    s.wait_n_clocks(WAIT_AOM, 'Wait for AOM off')
    s.set_output_port(hd.external_control_port, [(EOM_2G, 0)], 'Disable initialization EOM')
    s.no_init_time = s.trigger_out([hd.PMT_counter_reset], 'Reset PMT counter')
    s.nop()
    s.set_output_port(hd.counter_control_port, [(hd.PMT_counter_enable, 1)], 'Start PMT counter')
    s.set_output_port(hd.external_control_port, [(AOM, 1)], 'Start Detection')
    s.wait_n_clocks(WAIT_AOM, 'Wait for AOM on')
    s.repeat_detect = s.wait_n_clocks(T_det, 'Detection')
    s.set_output_port(hd.counter_control_port, [(hd.PMT_counter_enable, 0)], 'Stop PMT counter')
    s.read_counter(measured_PMT_R, hd.PMT_counter_result)
    s.write_to_fifo(run_counter_R, init_time_index_R, measured_PMT_R, 5, 'Store data')
    s.set_output_port(hd.external_control_port, [(EOM_14G_1, 1), (EOM_14G_2, 1), (AOM, 1)], 'Resume Cooling')
    s.add(run_counter_R, run_counter_R, 1)
    s.branch_if_less_than('repeat_run', run_counter_R, N_average, 'Repeat trial')
    s.load_immediate(run_counter_R, 0)
    s.add(init_time_index_R, init_time_index_R, 1)
    s.branch_if_less_than('repeat_run', init_time_index_R, N_init_control, 'Advance initialization time')
    s.stop()
    return s
