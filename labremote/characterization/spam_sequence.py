"""Adapted original SPAM builder; no host/device connection code."""
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram, reg

def build_program(qubit_control_index, config, hd):
    T_cool = config['T_cool']
    T_cool_repeat = config['T_cool_repeat']
    WAIT_AOM = config['WAIT_AOM']
    T_init = config['T_init']
    T_det = config['T_det']
    T_mw_time = config['T_PI']
    N_average = config['N_average']
    N_threshold = config['N_threshold']
    MW_12G = hd.MW_out
    EOM_14G_1 = hd.EOM_7G_1_out
    EOM_14G_2 = hd.EOM_7G_2_out
    EOM_2G = hd.EOM_2G_out
    AOM = hd.AOM_out
    MAX_DATA_MEMORY = 1024
    MAX_REG = 32
    MAX_DATA = N_average
    temp_R = reg[0]
    memory_pointer_R = reg[1]
    AOM_cooling_R = reg[2]
    microwave_condition_R = reg[4]
    count_microwave_R = reg[5]
    count_measured_PMT_R = reg[6]
    run_counter_R = reg[8]
    transfer1_R = reg[12]
    transfer_pointer_R = reg[10]
    s = SequencerProgram()
    s.set_output_port(hd.external_control_port, [(MW_12G, 0)])
    s.set_output_port(hd.external_control_port, [(EOM_14G_1, 1), (EOM_14G_2, 1), (AOM, 1)], 'laser setup')
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.load_immediate(microwave_condition_R, qubit_control_index)
    s.memory_initialization = s.store_word_to_memory(memory_pointer_R, temp_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.branch_if_less_than('memory_initialization', memory_pointer_R, MAX_DATA)
    s.load_immediate(run_counter_R, 0, 'reg[0] will be used for run number')
    s.load_immediate(memory_pointer_R, 0)
    s.trial = s.load_immediate(count_microwave_R, 0, 'reg[0] will be used for run number')
    s.load_immediate(AOM_cooling_R, 0)
    s.cooling = s.set_output_port(hd.external_control_port, [(EOM_14G_1, 1), (EOM_14G_2, 1), (AOM, 1)], 'Start Cooling')
    s.wait_n_clocks(T_cool, '1US=')
    s.add(AOM_cooling_R, AOM_cooling_R, 1, 'count_cooling_R++')
    s.branch_if_less_than('cooling', AOM_cooling_R, T_cool_repeat, 'Wait for 1ms')
    s.init = s.set_output_port(hd.external_control_port, [(EOM_14G_1, 0), (EOM_14G_2, 0), (EOM_2G, 1)], 'Start Initialization')
    s.wait_n_clocks(T_init, 'Initialization for 50000 * 10 ns = 0.5 ms')
    s.set_output_port(hd.external_control_port, [(AOM, 0)], 'End Initialization')
    s.wait_n_clocks(WAIT_AOM, 'Wait for the AOM completely off')
    s.set_output_port(hd.external_control_port, [(EOM_2G, 0)], 'End Initialization')
    s.branch_if_equal('final_detection', microwave_condition_R, 0, 'MW off for condition 0; pi pulse for condition 1')
    s.set_output_port(hd.external_control_port, [(MW_12G, 1)], 'Start pi pulse')
    s.repeat_microwave = s.wait_n_clocks(T_mw_time - 7, '1US=')
    s.set_output_port(hd.external_control_port, [(MW_12G, 0)], 'Stop pi pulse')
    s.final_detection = s.trigger_out([hd.PMT_counter_reset], 'Reset single counter')
    s.set_output_port(hd.counter_control_port, [(hd.PMT_counter_enable, 1)], 'Start counter')
    s.set_output_port(hd.external_control_port, [(EOM_14G_1, 0), (EOM_14G_2, 0), (AOM, 1)], 'Start Detection')
    s.wait_n_clocks(T_det, 'Detecting')
    s.set_output_port(hd.counter_control_port, [(hd.PMT_counter_enable, 0)], 'Stop counter')
    s.read_counter(count_measured_PMT_R, hd.PMT_counter_result)
    s.set_output_port(hd.external_control_port, [(EOM_14G_1, 1), (EOM_14G_2, 1), (AOM, 1)], 'Start Detection')
    s.add(run_counter_R, run_counter_R, 1, 'run_counter_R++')
    s.store_data = s.store_word_to_memory(memory_pointer_R, count_measured_PMT_R, 'store count')
    s.add(memory_pointer_R, memory_pointer_R, 1, 'go to next frame')
    s.decide_repeat = s.branch_if_less_than('trial', run_counter_R, N_average)
    s.set_output_port(hd.external_control_port, [(EOM_14G_1, 1), (EOM_14G_2, 1), (AOM, 1)], 'Cooling during transfer')
    s.load_immediate(transfer_pointer_R, 0, 'Readout address; memory_pointer_R retains N_success')
    s.transfer_repeat = s.load_word_from_memory(transfer1_R, transfer_pointer_R)
    s.write_to_fifo(memory_pointer_R, transfer_pointer_R, transfer1_R, 10)
    s.add(transfer_pointer_R, transfer_pointer_R, 1)
    s.branch_if_less_than('transfer_repeat', transfer_pointer_R, MAX_DATA)
    s.stop()
    return s
