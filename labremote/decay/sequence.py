"""Adapted pulse timing from the four supplied decay scripts; no host-side effects."""
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram,reg
from .config import set_auxiliary

def build_171_single(config,hd):
    MAX_TIME_DIFFERENCE=config['MAX_TIME_DIFFERENCE']
    waiting_time_for_stopwatch=config['waiting_time_for_stopwatch']
    waiting_time_for_AOM_off=config['waiting_time_for_AOM_off']
    waiting_time_for_AOM_on=config['waiting_time_for_AOM_on']
    run_number=config['run_number']
    outer_loop_in_fpga=config['outer_loop_in_fpga']
    wo_cooling_number=config['wo_cooling_number']
    TIME_COOL=config['TIME_COOL']
    TIME_INIT=config['TIME_INIT']
    THRESHOLD=config['SIGNAL_THRESHOLD']
    SIGNAL_THRESHOLD=config['SIGNAL_THRESHOLD']
    PMT2_MEMORY_ADDRESS=MAX_TIME_DIFFERENCE
    MAX_DATA=2*MAX_TIME_DIFFERENCE
    run_counter_R = reg[0]
    AOM_cooling_R = reg[1]
    sw_flags_R = reg[2]
    pulse_trigger_timing_R = reg[3]
    PMT1_timing_R = reg[4]
    memory_pointer_R = reg[10]
    temp_R = reg[11]
    transfer1_R = reg[12]
    transfer2_R = reg[13]
    transfer3_R = reg[14]
    outer_loop_R = reg[16]
    wo_cooling_number_R = reg[17]
    time_diff_R = reg[18]
    s = SequencerProgram()
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.memory_initialization = s.store_word_to_memory(memory_pointer_R, temp_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.branch_if_less_than('memory_initialization', memory_pointer_R, MAX_TIME_DIFFERENCE)
    s.load_immediate(AOM_cooling_R, 0)
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.load_immediate(run_counter_R, 0, 'reg[0] will be used for run number')
    s.load_immediate(outer_loop_R, 0, 'outer loop is for repeat more than 50000')
    s.load_immediate(wo_cooling_number_R, 0, 'this is for initalization imeediately without cooling ')
    set_auxiliary(s,config,start=True)
    s.cooling = s.set_output_port(hd.external_control_port, [(hd.EOM_7G1_out, 1), (hd.EOM_7G2_out, 1), (hd.AOM_out, 1)], 'Start Cooling')
    s.wait_n_clocks(TIME_COOL, '1US=')
    s.init = s.set_output_port(hd.external_control_port, [(hd.EOM_7G1_out, 0), (hd.EOM_7G2_out, 0), (hd.EOM_2G_out, 1)], 'Start Initialization')
    s.wait_n_clocks(TIME_INIT - 3 - 2, '1US=')
    s.set_output_port(hd.external_control_port, [(hd.AOM_out, 0)], 'End Initialization')
    s.wait_n_clocks(waiting_time_for_AOM_off - 3, 'Wait for completely turning off the AOM')
    s.set_output_port(hd.external_control_port, [(hd.EOM_2G_out, 0)], 'End Initialization')
    s.trial = s.set_output_port(hd.external_control_port, [(hd.TRIG_out, 1)])
    s.set_output_port(hd.external_control_port, [(hd.TRIG_out, 0)])
    s.trigger_out([hd.PMT1_stopwatch_reset, hd.SYNC_stopwatch_reset], 'Reset stopwatches')
    s.nop()
    s.trigger_out([hd.PMT1_stopwatch_start, hd.SYNC_stopwatch_start], 'Start stopwatches')
    s.wait_n_clocks(waiting_time_for_stopwatch - 3, 'Wait for Stopwatch')
    s.read_counter(sw_flags_R, hd.Trigger_level, 'Read status of stopwatches')
    s.read_counter(pulse_trigger_timing_R, hd.SYNC_stopwatch_result, 'Read pulse trigger stopwatch result')
    s.read_counter(PMT1_timing_R, hd.PMT1_stopwatch_result, 'Read PMTA stopwatch result')
    s.branch_if_equal_with_mask('decide_init',sw_flags_R,0,1 << hd.SYNC_stopwatch_stopped_TLI)
    s.check_PMT_triggered = s.branch_if_equal_with_mask('decide_init', sw_flags_R, 0, 1 << hd.PMT1_stopwatch_stopped_TLI)
    s.subtract(time_diff_R, PMT1_timing_R, pulse_trigger_timing_R)
    s.branch_if_less_than('store_PMT1', time_diff_R, MAX_TIME_DIFFERENCE)
    s.jump('decide_init')
    s.store_PMT1 = s.branch_if_less_than('decide_init', time_diff_R, THRESHOLD)
    s.load_word_from_memory(temp_R, time_diff_R)
    s.add(temp_R, temp_R, 1)
    s.store_word_to_memory(time_diff_R, temp_R)
    s.decide_init = s.set_output_port(hd.external_control_port, [(hd.EOM_7G1_out, 1), (hd.EOM_7G2_out, 1), (hd.AOM_out, 1)], 'cooling short time')
    s.wait_n_clocks(waiting_time_for_AOM_on - 3, 'Wait for completely turning on the AOM')
    s.load_immediate(AOM_cooling_R, 0)
    s.add(wo_cooling_number_R, wo_cooling_number_R, 1, 'run_counter_R++')
    s.branch_if_less_than('init', wo_cooling_number_R, wo_cooling_number)
    s.decide_repeat = s.load_immediate(wo_cooling_number_R, 0)
    s.add(run_counter_R, run_counter_R, 1, 'run_counter_R++')
    s.branch_if_less_than('cooling', run_counter_R, run_number)
    s.add(outer_loop_R, outer_loop_R, 1, 'run_counter_R++')
    s.load_immediate(run_counter_R, 0, 'reset the run counter')
    s.branch_if_less_than('cooling', outer_loop_R, outer_loop_in_fpga)
    s.transfer_statistics = s.set_output_port(hd.external_control_port, [(hd.AOM_out, 1)], 'Start Cooling')
    s.load_immediate(memory_pointer_R, 0, 'memory_pointer_R is used as address pointer and counter')
    s.transfer_repeat = s.load_word_from_memory(transfer1_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.load_word_from_memory(transfer2_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.load_word_from_memory(transfer3_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.write_to_fifo(transfer1_R, transfer2_R, transfer3_R, 100)
    s.branch_if_less_than('transfer_repeat', memory_pointer_R, MAX_TIME_DIFFERENCE)
    s.stop()
    return s

def build_174_single(config,hd):
    MAX_TIME_DIFFERENCE=config['MAX_TIME_DIFFERENCE']
    waiting_time_for_stopwatch=config['waiting_time_for_stopwatch']
    waiting_time_for_AOM_off=config['waiting_time_for_AOM_off']
    waiting_time_for_AOM_on=config['waiting_time_for_AOM_on']
    run_number=config['run_number']
    outer_loop_in_fpga=config['outer_loop_in_fpga']
    wo_cooling_number=config['wo_cooling_number']
    TIME_COOL=config['TIME_COOL']
    TIME_INIT=config['TIME_INIT']
    THRESHOLD=config['SIGNAL_THRESHOLD']
    SIGNAL_THRESHOLD=config['SIGNAL_THRESHOLD']
    PMT2_MEMORY_ADDRESS=MAX_TIME_DIFFERENCE
    MAX_DATA=2*MAX_TIME_DIFFERENCE
    run_counter_R = reg[0]
    AOM_cooling_R = reg[1]
    sw_flags_R = reg[2]
    pulse_trigger_timing_R = reg[3]
    PMT1_timing_R = reg[4]
    memory_pointer_R = reg[10]
    temp_R = reg[11]
    transfer1_R = reg[12]
    transfer2_R = reg[13]
    transfer3_R = reg[14]
    outer_loop_R = reg[16]
    wo_cooling_number_R = reg[17]
    time_diff_R = reg[18]
    s = SequencerProgram()
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.memory_initialization = s.store_word_to_memory(memory_pointer_R, temp_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.branch_if_less_than('memory_initialization', memory_pointer_R, MAX_TIME_DIFFERENCE)
    s.load_immediate(AOM_cooling_R, 0)
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.load_immediate(run_counter_R, 0, 'reg[0] will be used for run number')
    s.load_immediate(outer_loop_R, 0, 'outer loop is for repeat more than 50000')
    s.load_immediate(wo_cooling_number_R, 0, 'this is for initalization imeediately without cooling ')
    set_auxiliary(s,config,start=True)
    s.cooling = s.set_output_port(hd.external_control_port, [(hd.AOM_out, 1)], 'Start Cooling')
    s.wait_n_clocks(TIME_COOL, '1US=')
    s.init = s.set_output_port(hd.external_control_port, [(hd.AOM_out, 1)], 'Start Cooling')
    s.wait_n_clocks(TIME_INIT - 3 - 2, '1US=')
    s.set_output_port(hd.external_control_port, [(hd.AOM_out, 0)], 'End Initialization')
    s.wait_n_clocks(waiting_time_for_AOM_off - 3, 'Wait for completely turning off the AOM')
    s.trial = s.set_output_port(hd.external_control_port, [(hd.TRIG_out, 1)])
    s.set_output_port(hd.external_control_port, [(hd.TRIG_out, 0)])
    s.trigger_out([hd.PMT1_stopwatch_reset, hd.SYNC_stopwatch_reset], 'Reset stopwatches')
    s.nop()
    s.trigger_out([hd.PMT1_stopwatch_start, hd.SYNC_stopwatch_start], 'Start stopwatches')
    s.wait_n_clocks(waiting_time_for_stopwatch - 3, 'Wait for Stopwatch')
    s.read_counter(sw_flags_R, hd.Trigger_level, 'Read status of stopwatches')
    s.read_counter(pulse_trigger_timing_R, hd.SYNC_stopwatch_result, 'Read pulse trigger stopwatch result')
    s.read_counter(PMT1_timing_R, hd.PMT1_stopwatch_result, 'Read PMTA stopwatch result')
    s.branch_if_equal_with_mask('decide_init',sw_flags_R,0,1 << hd.SYNC_stopwatch_stopped_TLI)
    s.check_PMT_triggered = s.branch_if_equal_with_mask('decide_init', sw_flags_R, 0, 1 << hd.PMT1_stopwatch_stopped_TLI)
    s.subtract(time_diff_R, PMT1_timing_R, pulse_trigger_timing_R)
    s.branch_if_less_than('store_PMT1', time_diff_R, MAX_TIME_DIFFERENCE)
    s.jump('decide_init')
    s.store_PMT1 = s.branch_if_less_than('decide_init', time_diff_R, THRESHOLD)
    s.load_word_from_memory(temp_R, time_diff_R)
    s.add(temp_R, temp_R, 1)
    s.store_word_to_memory(time_diff_R, temp_R)
    s.decide_init = s.set_output_port(hd.external_control_port, [(hd.AOM_out, 1)], 'cooling short time')
    s.wait_n_clocks(waiting_time_for_AOM_on - 3, 'Wait for completely turning on the AOM')
    s.load_immediate(AOM_cooling_R, 0)
    s.add(wo_cooling_number_R, wo_cooling_number_R, 1, 'run_counter_R++')
    s.branch_if_less_than('init', wo_cooling_number_R, wo_cooling_number)
    s.decide_repeat = s.load_immediate(wo_cooling_number_R, 0)
    s.add(run_counter_R, run_counter_R, 1, 'run_counter_R++')
    s.branch_if_less_than('cooling', run_counter_R, run_number)
    s.add(outer_loop_R, outer_loop_R, 1, 'run_counter_R++')
    s.load_immediate(run_counter_R, 0, 'reset the run counter')
    s.branch_if_less_than('cooling', outer_loop_R, outer_loop_in_fpga)
    s.transfer_statistics = s.set_output_port(hd.external_control_port, [(hd.AOM_out, 1)], 'Start Cooling')
    s.load_immediate(memory_pointer_R, 0, 'memory_pointer_R is used as address pointer and counter')
    s.transfer_repeat = s.load_word_from_memory(transfer1_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.load_word_from_memory(transfer2_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.load_word_from_memory(transfer3_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.write_to_fifo(transfer1_R, transfer2_R, transfer3_R, 100)
    s.branch_if_less_than('transfer_repeat', memory_pointer_R, MAX_TIME_DIFFERENCE)
    s.stop()
    return s

def build_171_dual(config,hd):
    MAX_TIME_DIFFERENCE=config['MAX_TIME_DIFFERENCE']
    waiting_time_for_stopwatch=config['waiting_time_for_stopwatch']
    waiting_time_for_AOM_off=config['waiting_time_for_AOM_off']
    waiting_time_for_AOM_on=config['waiting_time_for_AOM_on']
    run_number=config['run_number']
    outer_loop_in_fpga=config['outer_loop_in_fpga']
    wo_cooling_number=config['wo_cooling_number']
    TIME_COOL=config['TIME_COOL']
    TIME_INIT=config['TIME_INIT']
    THRESHOLD=config['SIGNAL_THRESHOLD']
    SIGNAL_THRESHOLD=config['SIGNAL_THRESHOLD']
    PMT2_MEMORY_ADDRESS=MAX_TIME_DIFFERENCE
    MAX_DATA=2*MAX_TIME_DIFFERENCE
    run_counter_R = reg[0]
    AOM_cooling_R = reg[1]
    sw_flags_R = reg[2]
    pulse_trigger_timing_R = reg[3]
    PMT1_timing_R = reg[4]
    PMT2_timing_R = reg[5]
    memory_pointer_R = reg[6]
    temp_R = reg[7]
    transfer1_R = reg[8]
    transfer2_R = reg[9]
    transfer3_R = reg[10]
    outer_loop_R = reg[11]
    wo_cooling_number_R = reg[12]
    time_diff1_R = reg[13]
    time_diff2_R = reg[14]
    s = SequencerProgram()
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.memory_initialization = s.store_word_to_memory(memory_pointer_R, temp_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.branch_if_less_than('memory_initialization', memory_pointer_R, MAX_DATA)
    set_auxiliary(s,config,start=True)
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.load_immediate(run_counter_R, 0, 'reg[0] will be used for run number')
    s.load_immediate(outer_loop_R, 0, 'outer loop is for repeat more than 50000')
    s.load_immediate(wo_cooling_number_R, 0, 'this is for initalization imeediately without cooling ')
    s.cooling = s.set_output_port(hd.external_control_port, [(hd.EOM_7G1_out, 1), (hd.EOM_7G2_out, 1), (hd.AOM_out, 1)], 'Start Cooling')
    s.wait_n_clocks(TIME_COOL, '1US=')
    s.init = s.set_output_port(hd.external_control_port, [(hd.EOM_7G1_out, 0), (hd.EOM_7G2_out, 0), (hd.EOM_2G_out, 1)], 'Start Initialization')
    s.wait_n_clocks(TIME_INIT - 3 - 2, '1US=')
    s.set_output_port(hd.external_control_port, [(hd.EOM_2G_out, 0), (hd.AOM_out, 0)], 'End Initialization')
    s.wait_n_clocks(waiting_time_for_AOM_off - 3, 'Wait for completely turning off the AOM')
    s.trial = s.set_output_port(hd.external_control_port, [(hd.TRIG_out, 1)])
    s.set_output_port(hd.external_control_port, [(hd.TRIG_out, 0)])
    s.trigger_out([hd.PMT1_stopwatch_reset, hd.PMT2_stopwatch_reset, hd.SYNC_stopwatch_reset], 'Reset stopwatches')
    s.nop()
    s.trigger_out([hd.PMT1_stopwatch_start, hd.PMT2_stopwatch_start, hd.SYNC_stopwatch_start], 'Start stopwatches')
    s.wait_n_clocks(waiting_time_for_stopwatch - 3, 'Wait for Stopwatch')
    s.read_counter(sw_flags_R, hd.Trigger_level, 'Read status of stopwatches')
    s.read_counter(pulse_trigger_timing_R, hd.SYNC_stopwatch_result, 'Read pulse trigger stopwatch result')
    s.read_counter(PMT1_timing_R, hd.PMT1_stopwatch_result, 'Read PMT1 stopwatch result')
    s.read_counter(PMT2_timing_R, hd.PMT2_stopwatch_result, 'Read PMT2 stopwatch result')
    s.branch_if_equal_with_mask('decide_init',sw_flags_R,0,1 << hd.SYNC_stopwatch_stopped_TLI)
    s.set_output_port(hd.external_control_port, [(hd.EOM_7G1_out, 1), (hd.EOM_7G2_out, 1), (hd.AOM_out, 1)], 'Start Cooling')
    s.check_PMT1_triggered = s.branch_if_equal_with_mask('check_PMT2_triggered', sw_flags_R, 0, 1 << hd.PMT1_stopwatch_stopped_TLI)
    s.subtract(time_diff1_R, PMT1_timing_R, pulse_trigger_timing_R)
    s.branch_if_less_than('store_PMT1', time_diff1_R, MAX_TIME_DIFFERENCE)
    s.jump('check_PMT2_triggered')
    s.store_PMT1 = s.branch_if_less_than('check_PMT2_triggered', time_diff1_R, SIGNAL_THRESHOLD)
    s.load_word_from_memory(temp_R, time_diff1_R)
    s.add(temp_R, temp_R, 1)
    s.store_word_to_memory(time_diff1_R, temp_R)
    s.check_PMT2_triggered = s.branch_if_equal_with_mask('decide_init', sw_flags_R, 0, 1 << hd.PMT2_stopwatch_stopped_TLI)
    s.subtract(time_diff2_R, PMT2_timing_R, pulse_trigger_timing_R)
    s.branch_if_less_than('store_PMT2', time_diff2_R, MAX_TIME_DIFFERENCE)
    s.jump('decide_init')
    s.store_PMT2 = s.branch_if_less_than('decide_init', time_diff2_R, SIGNAL_THRESHOLD)
    s.add(time_diff2_R, time_diff2_R, PMT2_MEMORY_ADDRESS)
    s.load_word_from_memory(temp_R, time_diff2_R)
    s.add(temp_R, temp_R, 1)
    s.store_word_to_memory(time_diff2_R, temp_R)
    s.decide_init = s.set_output_port(hd.external_control_port, [(hd.EOM_7G1_out, 1), (hd.EOM_7G2_out, 1), (hd.AOM_out, 1)], 'cooling short time')
    s.wait_n_clocks(waiting_time_for_AOM_off - 3, 'Wait for completely turning on the AOM')
    s.add(wo_cooling_number_R, wo_cooling_number_R, 1, 'run_counter_R++')
    s.branch_if_less_than('init', wo_cooling_number_R, wo_cooling_number)
    s.wait_n_clocks(5, '1US=')
    s.decide_repeat = s.load_immediate(wo_cooling_number_R, 0)
    s.add(run_counter_R, run_counter_R, 1, 'run_counter_R++')
    s.branch_if_less_than('cooling', run_counter_R, run_number)
    s.add(outer_loop_R, outer_loop_R, 1, 'run_counter_R++')
    s.load_immediate(run_counter_R, 0, 'reset the run counter')
    s.branch_if_less_than('cooling', outer_loop_R, outer_loop_in_fpga)
    s.transfer_statistics = s.set_output_port(hd.external_control_port, [(hd.EOM_7G1_out, 1), (hd.EOM_7G2_out, 1), (hd.AOM_out, 1)], 'Start Cooling')
    s.load_immediate(memory_pointer_R, 0, 'memory_pointer_R is used as address pointer and counter')
    s.transfer_repeat = s.load_word_from_memory(transfer1_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.load_word_from_memory(transfer2_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.load_word_from_memory(transfer3_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.write_to_fifo(transfer1_R, transfer2_R, transfer3_R, 100)
    s.branch_if_less_than('transfer_repeat', memory_pointer_R, MAX_DATA)
    s.stop()
    return s

def build_174_dual(config,hd):
    MAX_TIME_DIFFERENCE=config['MAX_TIME_DIFFERENCE']
    waiting_time_for_stopwatch=config['waiting_time_for_stopwatch']
    waiting_time_for_AOM_off=config['waiting_time_for_AOM_off']
    waiting_time_for_AOM_on=config['waiting_time_for_AOM_on']
    run_number=config['run_number']
    outer_loop_in_fpga=config['outer_loop_in_fpga']
    wo_cooling_number=config['wo_cooling_number']
    TIME_COOL=config['TIME_COOL']
    TIME_INIT=config['TIME_INIT']
    THRESHOLD=config['SIGNAL_THRESHOLD']
    SIGNAL_THRESHOLD=config['SIGNAL_THRESHOLD']
    PMT2_MEMORY_ADDRESS=MAX_TIME_DIFFERENCE
    MAX_DATA=2*MAX_TIME_DIFFERENCE
    run_counter_R = reg[0]
    AOM_cooling_R = reg[1]
    sw_flags_R = reg[2]
    pulse_trigger_timing_R = reg[3]
    PMT1_timing_R = reg[4]
    PMT2_timing_R = reg[5]
    memory_pointer_R = reg[6]
    temp_R = reg[7]
    transfer1_R = reg[8]
    transfer2_R = reg[9]
    transfer3_R = reg[10]
    outer_loop_R = reg[11]
    wo_cooling_number_R = reg[12]
    time_diff1_R = reg[13]
    time_diff2_R = reg[14]
    s = SequencerProgram()
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.memory_initialization = s.store_word_to_memory(memory_pointer_R, temp_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.branch_if_less_than('memory_initialization', memory_pointer_R, MAX_DATA)
    set_auxiliary(s,config,start=True)
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.load_immediate(run_counter_R, 0, 'reg[0] will be used for run number')
    s.load_immediate(outer_loop_R, 0, 'outer loop is for repeat more than 50000')
    s.load_immediate(wo_cooling_number_R, 0, 'this is for initalization imeediately without cooling ')
    s.cooling = s.set_output_port(hd.external_control_port, [(hd.AOM_out, 1)], 'Start Cooling')
    s.wait_n_clocks(TIME_COOL, '1US=')
    s.init = s.set_output_port(hd.external_control_port, [(hd.AOM_out, 1)], 'Start Cooling')
    s.wait_n_clocks(TIME_INIT - 3 - 2, '1US=')
    s.set_output_port(hd.external_control_port, [(hd.AOM_out, 0)], 'End Initialization')
    s.wait_n_clocks(waiting_time_for_AOM_off - 3, 'Wait for completely turning off the AOM')
    s.trial = s.set_output_port(hd.external_control_port, [(hd.TRIG_out, 1)])
    s.set_output_port(hd.external_control_port, [(hd.TRIG_out, 0)])
    s.trigger_out([hd.PMT1_stopwatch_reset, hd.PMT2_stopwatch_reset, hd.SYNC_stopwatch_reset], 'Reset stopwatches')
    s.nop()
    s.trigger_out([hd.PMT1_stopwatch_start, hd.PMT2_stopwatch_start, hd.SYNC_stopwatch_start], 'Start stopwatches')
    s.wait_n_clocks(waiting_time_for_stopwatch - 3, 'Wait for Stopwatch')
    s.read_counter(sw_flags_R, hd.Trigger_level, 'Read status of stopwatches')
    s.read_counter(pulse_trigger_timing_R, hd.SYNC_stopwatch_result, 'Read pulse trigger stopwatch result')
    s.read_counter(PMT1_timing_R, hd.PMT1_stopwatch_result, 'Read PMT1 stopwatch result')
    s.read_counter(PMT2_timing_R, hd.PMT2_stopwatch_result, 'Read PMT2 stopwatch result')
    s.branch_if_equal_with_mask('decide_init',sw_flags_R,0,1 << hd.SYNC_stopwatch_stopped_TLI)
    s.set_output_port(hd.external_control_port, [(hd.AOM_out, 1)], 'Start Cooling')
    s.check_PMT1_triggered = s.branch_if_equal_with_mask('check_PMT2_triggered', sw_flags_R, 0, 1 << hd.PMT1_stopwatch_stopped_TLI)
    s.subtract(time_diff1_R, PMT1_timing_R, pulse_trigger_timing_R)
    s.branch_if_less_than('store_PMT1', time_diff1_R, MAX_TIME_DIFFERENCE)
    s.jump('check_PMT2_triggered')
    s.store_PMT1 = s.branch_if_less_than('check_PMT2_triggered', time_diff1_R, THRESHOLD)
    s.load_word_from_memory(temp_R, time_diff1_R)
    s.add(temp_R, temp_R, 1)
    s.store_word_to_memory(time_diff1_R, temp_R)
    s.check_PMT2_triggered = s.branch_if_equal_with_mask('decide_init', sw_flags_R, 0, 1 << hd.PMT2_stopwatch_stopped_TLI)
    s.subtract(time_diff2_R, PMT2_timing_R, pulse_trigger_timing_R)
    s.branch_if_less_than('store_PMT2', time_diff2_R, MAX_TIME_DIFFERENCE)
    s.jump('decide_init')
    s.store_PMT2 = s.branch_if_less_than('decide_init', time_diff2_R, THRESHOLD)
    s.add(time_diff2_R, time_diff2_R, PMT2_MEMORY_ADDRESS)
    s.load_word_from_memory(temp_R, time_diff2_R)
    s.add(temp_R, temp_R, 1)
    s.store_word_to_memory(time_diff2_R, temp_R)
    s.decide_init = s.set_output_port(hd.external_control_port, [(hd.AOM_out, 1)], 'cooling short time')
    s.wait_n_clocks(waiting_time_for_AOM_off - 3, 'Wait for completely turning on the AOM')
    s.add(wo_cooling_number_R, wo_cooling_number_R, 1, 'run_counter_R++')
    s.branch_if_less_than('init', wo_cooling_number_R, wo_cooling_number)
    s.wait_n_clocks(5, '1US=')
    s.decide_repeat = s.load_immediate(wo_cooling_number_R, 0)
    s.add(run_counter_R, run_counter_R, 1, 'run_counter_R++')
    s.branch_if_less_than('cooling', run_counter_R, run_number)
    s.add(outer_loop_R, outer_loop_R, 1, 'run_counter_R++')
    s.load_immediate(run_counter_R, 0, 'reset the run counter')
    s.branch_if_less_than('cooling', outer_loop_R, outer_loop_in_fpga)
    s.transfer_statistics = s.set_output_port(hd.external_control_port, [(hd.AOM_out, 1)], 'Start Cooling')
    s.load_immediate(memory_pointer_R, 0, 'memory_pointer_R is used as address pointer and counter')
    s.transfer_repeat = s.load_word_from_memory(transfer1_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.load_word_from_memory(transfer2_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.load_word_from_memory(transfer3_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.write_to_fifo(transfer1_R, transfer2_R, transfer3_R, 100)
    s.branch_if_less_than('transfer_repeat', memory_pointer_R, MAX_DATA)
    s.stop()
    return s

def build_program(config):
    from .config import hardware
    return globals()["build_"+config["mode"]](config,hardware(config))
