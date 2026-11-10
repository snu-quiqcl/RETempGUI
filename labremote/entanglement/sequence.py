# -*- coding: utf-8 -*-
"""Sequencer only: no serial/network access, file saving, plots, or GUI.
Configure the external MW source separately before running MW-detuned mode.
Defaults use MW v1.07 excitation settings and flip-mirror reference readout.
FIFO v2: full A/C arrival histograms x120 each, gated coincidence x240,
six state words, then overflow/version metadata. No per-event arrival records.
"""
import math
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram, reg
from labremote.devices.fpga.vendor import HardwareDefinition_remote_ent_test_ec as hd


def build_sequence(basis='mw_detuned', *, half_pi_ea_us=40.55, half_pi_ec_us=35.29,
                   detuning_hz=-2000.0, phase_magnitude_deg=175.0,
                   groups_per_loop=50000, fpga_loops=10, inner_trials=10,
                   mirror_wait_repeats=1200, detection_us=100.0,
                   cooling_us=5.0, initialization_us=1.0,
                   decay_lower_a=86, decay_lower_c=86,
                   coincidence_half_window_bins=10, aom_off_us=.30, stopwatch_wait_us=.21):
    if basis not in ('zz', 'mw_detuned'):
        raise ValueError('basis must be zz or mw_detuned')
    for value in (groups_per_loop, fpga_loops, inner_trials, mirror_wait_repeats):
        if type(value) is not int or not 1 <= value <= 65535:
            raise ValueError('Loop counts must be integers in 1..65535')
    for value in (detection_us, cooling_us, initialization_us, half_pi_ea_us, half_pi_ec_us):
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Durations must be positive and finite')
    if not 1 <= round(detection_us * 100) <= 65535:
        raise ValueError('Detection duration exceeds a single wait instruction')
    for value in (cooling_us, initialization_us):
        if not 0 <= round(value * 100) - 5 <= 65535:
            raise ValueError('Cooling/initialization wait is outside FPGA range')
    for value in (decay_lower_a, decay_lower_c):
        if type(value) is not int or not 0 <= value < 120:
            raise ValueError('Decay lower bin must be in 0..119')
    if type(coincidence_half_window_bins) is not int or not 1 <= coincidence_half_window_bins <= 120:
        raise ValueError('Coincidence half window must be in 1..120 bins')

    #declare register alias
    run_counter_R            = reg[0]
    AOM_cooling_R            = reg[1]
    sw_flags_R               = reg[2]
    pulse_trigger_timing_R   = reg[3]
    PMTA_timing_R            = reg[4]
    PMTC_timing_R            = reg[5]
    time_diff_A_R            = reg[6]
    time_diff_C_R            = reg[7]
    coin_flag_R              = reg[8]
    state_add_R              = reg[9]
    memory_pointer_R         = reg[10]
    temp_R                   = reg[11]
    transfer1_R              = reg[12]
    transfer2_R              = reg[13]
    transfer3_R              = reg[14]
    time_delta_R             = reg[15]
    outer_loop_R             = reg[16]
    PMTA_counter_R           = reg[17]
    PMTC_counter_R           = reg[18]
    det_A_R                  = reg[19]
    det_C_R                  = reg[20]
    wo_cooling_number_R      = reg[21]
    detect_flag_R            = reg[22]
    PMTFA_counter_R          = reg[23]
    PMTFC_counter_R          = reg[24]
    wait_flip_count_R        = reg[25]

    #delcare variable 
    MAX_TIME_DIFFERENCE = 120
    PMTA_BIAS = 0
    PMTC_BIAS =MAX_TIME_DIFFERENCE
    COINCIDENCE_BIAS = 2*MAX_TIME_DIFFERENCE # = 240
    STATEA_BIAS = 4*MAX_TIME_DIFFERENCE
    STATEC_BIAS = 4*MAX_TIME_DIFFERENCE + 1
    STATE_SIZE = 6
    MAX_DATA = 4*MAX_TIME_DIFFERENCE + STATE_SIZE # 486 words; 162 FIFO triples

    waiting_time_for_stopwatch = int(round(stopwatch_wait_us * 100)) #minimum is 4
    waiting_time_for_AOM_off = int(round(aom_off_us * 100)) #100=1us
    waiting_time_for_AOM_on = 30 #100=1us

    run_number = groups_per_loop
    outer_loop_in_fpga = fpga_loops
    wo_cooling_number = inner_trials 






    TIME_COOL = int(round(cooling_us * 100))
    TIME_INIT = int(round(initialization_us * 100))

    TIME_MW_EA = int(round(half_pi_ea_us * 100))
    TIME_MW_EC = int(round(half_pi_ec_us * 100))
    wait_time_phase = 0
    if basis == 'mw_detuned':
        if not math.isfinite(detuning_hz) or detuning_hz == 0:
            raise ValueError('MW phase-delay mode requires nonzero finite detuning')
        if not math.isfinite(phase_magnitude_deg) or phase_magnitude_deg < 0:
            raise ValueError('Phase magnitude must be finite and nonnegative')
        # Preserve original START-delay and truncation convention (10 ns clock).
        wait_time_phase = int(phase_magnitude_deg / 360 / abs(detuning_hz) * 1e8)

    THRESHOLD_A=decay_lower_a
    THRESHOLD_C=decay_lower_c

    TIME_WINDOW = coincidence_half_window_bins
    TIME_WINDOW_UP = MAX_TIME_DIFFERENCE + COINCIDENCE_BIAS + TIME_WINDOW # 120 + 240 - window = 360 - window
    TIME_WINDOW_LOW = MAX_TIME_DIFFERENCE + COINCIDENCE_BIAS - TIME_WINDOW # 360 + window
    T_500us = 50000
    repeat_delay_flipped = mirror_wait_repeats
    TIME_DETECT = int(round(detection_us * 100))  # Direct clocks, not 0.5-ms repeats.

    # Times are FPGA clocks (10 ns); pulse durations are RESONANT pi/2 times.
    # Keep original phase-magnitude/start-delay convention and timing compensation.
    # Actual TTL edge spacing must be verified on the installed FPGA.
    MW_EDGE_OVERHEAD_CLOCKS = 7

    def make_mw_events(ea_clocks, ec_clocks, start_gap_clocks, ea_pin, ec_pin):
        """Sort all edges, merging simultaneous edges, including EC ending first."""
        if any(type(v) is not int for v in (ea_clocks, ec_clocks, start_gap_clocks)):
            raise ValueError('MW timings must be integer clock counts')
        if ea_clocks <= 0 or ec_clocks <= 0 or start_gap_clocks < 0:
            raise ValueError('Positive durations and nonnegative start gap required')
        if ea_pin == ec_pin:
            raise ValueError('EA and EC require different MW output pins')
        edges = {}
        for tick, pin, state in ((0, ea_pin, 1), (ea_clocks, ea_pin, 0),
                                 (start_gap_clocks, ec_pin, 1),
                                 (start_gap_clocks + ec_clocks, ec_pin, 0)):
            edges.setdefault(tick, []).append((pin, state))
        events = sorted(edges.items())
        for (previous, _), (current, _) in zip(events, events[1:]):
            wait = current - previous - MW_EDGE_OVERHEAD_CLOCKS
            if not 0 <= wait <= 65535:
                raise ValueError(
                    f'MW edge gap {current - previous} clocks is unsupported with '
                    '7-clock timing compensation and 16-bit wait. '
                    'Change phase/duration; timing is never silently adjusted.')
        return events


    def emit_mw_events(sequence, port, events):
        previous = None
        for tick, changes in events:
            if previous is not None:
                sequence.wait_n_clocks(tick - previous - MW_EDGE_OVERHEAD_CLOCKS,
                                       'MW edge spacing; original compensation')
            sequence.set_output_port(port, changes, f'MW edge at relative clock {tick}')
            previous = tick


    MW_EVENTS = (make_mw_events(TIME_MW_EA, TIME_MW_EC, wait_time_phase,
                                hd.MW_A_out, hd.MW_C_out)
                 if basis == 'mw_detuned' else [])

    #sequencer code
    s = SequencerProgram()
    # First FPGA instruction for every basis: clear MW before memory initialization.
    s.set_output_port(hd.external_control_port,
                      [(hd.MW_A_out, 0), (hd.MW_C_out, 0)], 'Force MW OFF at entry')
    s.load_immediate(reg[26], 0)  # Histogram saturation flag.

    def increment_histogram(address, label):
        first = s.load_word_from_memory(temp_R, address)
        s.branch_if_less_than(label + '_increment', temp_R, 65535)
        s.load_immediate(reg[26], 1)
        s.jump(label + '_done')
        setattr(s, label + '_increment', s.add(temp_R, temp_R, 1))
        s.store_word_to_memory(address, temp_R)
        setattr(s, label + '_done', s.nop())
        return first


    def wait_for_mirror(label):
        # 1200 x 500 us ~= 600 ms plus loop instruction overhead (reference code).
        s.load_immediate(wait_flip_count_R, 0)
        setattr(s, label, s.wait_n_clocks(T_500us, 'Flip mirror settling'))
        s.add(wait_flip_count_R, wait_flip_count_R, 1)
        s.branch_if_less_than(label, wait_flip_count_R, repeat_delay_flipped)


    s.load_immediate(temp_R, 0) 
    s.load_immediate(memory_pointer_R, 0)

    #memory init, 0~max_time_diff_to_record init
    s.memory_initialization = \
    \
    s.store_word_to_memory(memory_pointer_R, temp_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.branch_if_less_than('memory_initialization', memory_pointer_R, MAX_DATA)

    #reset register
    s.load_immediate(AOM_cooling_R, 0) # reg[1] is for the cooling time
    s.load_immediate(temp_R, 0)
    s.load_immediate(memory_pointer_R, 0)
    s.load_immediate(coin_flag_R, 0)
    s.load_immediate(det_A_R, 0)
    s.load_immediate(det_C_R, 0)
    s.load_immediate(coin_flag_R, 0)

    #Reset run_number
    s.load_immediate(run_counter_R, 0, 'reg[0] will be used for run number')
    s.load_immediate(outer_loop_R, 0, 'outer loop is for repeat more than 50000')
    s.load_immediate(wo_cooling_number_R, 0, 'this is for initalization imeediately without cooling ')
    s.load_immediate(detect_flag_R, 0, 'this is for detection flag')

    #Address
    s.load_immediate(state_add_R, STATEA_BIAS)
    s.set_output_port(hd.external_control_port,
                      [(hd.MW_A_out, 0), (hd.MW_C_out, 0)], 'MW OFF at batch start')
    s.set_output_port(hd.counter_control_port,
                      [(hd.PMTFA_counter_enable, 0), (hd.PMTFC_counter_enable, 0)])
    s.set_output_port(hd.external_control_port,
                      [(hd.AOMA_out, 1), (hd.AOMC_out, 1),
                       (hd.EOM_7GA1_out, 1), (hd.EOM_7GA2_out, 1),
                       (hd.EOM_7GC1_out, 1), (hd.EOM_7GC2_out, 1),
                       (hd.EOM_2GA_out, 0), (hd.EOM_2GC_out, 0)], 'Cooling')
    s.set_output_port(hd.external_slow_port,
                      [(hd.AOMB_out, 1), (hd.AOMM_out, 1),
                       (hd.CCD_EC_out, 0), (hd.CCD_EA_out, 1)], 'Collection path')
    wait_for_mirror('wait_return_mirror')

    #Cooling stage
    #EOM 14.7GHz : EOM_14_7GHz on
    #AOM         : AOM_on_off on
    s.cooling = \
    \
    s.set_output_port(hd.external_control_port, [(hd.EOM_7GA1_out, 1), (hd.EOM_7GA2_out, 1), (hd.EOM_7GC1_out, 1), (hd.EOM_7GC2_out, 1)], 'Start Cooling')
    s.set_output_port(hd.external_control_port, [(hd.AOMA_out, 1), (hd.AOMC_out, 1)], 'Start Cooling')
    s.wait_n_clocks(TIME_COOL-3-2,'Cooling')


    #Initialization stage
    #EOM 14.7GHz : EOM_14_7GHz off
    #EOM 2.1GHz : EOM_2_1GHz on
    #AOM        :  AOM_on_off on
    s.init = \
    \
    s.set_output_port(hd.external_control_port, [(hd.EOM_7GA1_out, 0), (hd.EOM_7GA2_out, 0),(hd.EOM_7GC1_out, 0), (hd.EOM_7GC2_out, 0)], 'Start Initialization')
    s.set_output_port(hd.external_control_port, [(hd.EOM_2GA_out, 1), (hd.EOM_2GC_out, 1)], 'Start Initialization')
    s.wait_n_clocks(TIME_INIT-3-2,'Initialize')
    s.set_output_port(hd.external_control_port, [(hd.AOMA_out, 0),(hd.AOMC_out, 0)], 'AOM Off')
    s.wait_n_clocks(waiting_time_for_AOM_off-3, 'Wait for completely turning off the AOM')
    s.set_output_port(hd.external_control_port, [(hd.EOM_2GA_out, 0),(hd.EOM_2GC_out, 0)], 'End Initialization')

    #trigger picker
    s.trial = \
    \
    s.set_output_port(hd.external_control_port, [(hd.TRIG_out, 1)])
    s.set_output_port(hd.external_control_port, [(hd.TRIG_out, 0)])

    #start stop watch
    s.trigger_out([hd.PMTA_stopwatch_reset, hd.PMTC_stopwatch_reset, hd.SYNC_stopwatch_reset, ], 'Reset stopwatches')
    s.nop() # Between reset and start of the stopwatches, add at least one clock
    s.trigger_out([hd.PMTA_stopwatch_start, hd.PMTC_stopwatch_start, hd.SYNC_stopwatch_start, ], 'Start stopwatches')

    #wait for pmt
    s.wait_n_clocks(waiting_time_for_stopwatch-3, 'Wait for Stopwatch')

    # Collect the result of stopwatch measurements
    s.read_counter(sw_flags_R,              hd.Trigger_level, 'Read status of stopwatches')
    s.read_counter(pulse_trigger_timing_R,  hd.SYNC_stopwatch_result, 'Read pulse trigger stopwatch result')
    s.read_counter(PMTA_timing_R,           hd.PMTA_stopwatch_result, 'Read PMTA stopwatch result')
    s.read_counter(PMTC_timing_R,           hd.PMTC_stopwatch_result, 'Read PMTC stopwatch result')

    # Check if PMT A has arrived
    s.check_PMT_A_triggered = \
    \
    s.branch_if_equal_with_mask('check_PMT_C_triggered', sw_flags_R, \
        0 , 1 << hd.PMTA_stopwatch_stopped_TLI)
    s.subtract(time_diff_A_R, PMTA_timing_R, pulse_trigger_timing_R)
    s.branch_if_less_than('store_PMT_A', time_diff_A_R, MAX_TIME_DIFFERENCE)
    s.jump('check_PMT_C_triggered')

    # Preserve ALL in-range A arrivals; cutoff only controls coincidence eligibility.
    s.store_PMT_A = increment_histogram(time_diff_A_R, 'hist_a')
    s.branch_if_less_than('check_PMT_C_triggered', time_diff_A_R, THRESHOLD_A)
    s.add(coin_flag_R,coin_flag_R, 1)

    # Check if PMT C has arrived
    s.check_PMT_C_triggered = \
    \
    s.branch_if_equal_with_mask('decide_init', sw_flags_R, \
        0 , 1 << hd.PMTC_stopwatch_stopped_TLI)
    s.subtract(time_diff_C_R, PMTC_timing_R, pulse_trigger_timing_R)
    s.branch_if_less_than('store_PMT_C', time_diff_C_R, MAX_TIME_DIFFERENCE)
    s.jump('decide_init')

    # Preserve ALL in-range C arrivals. After biasing, compare against cutoff + bias.
    s.store_PMT_C = s.add(time_diff_C_R, time_diff_C_R, PMTC_BIAS)
    increment_histogram(time_diff_C_R, 'hist_c')
    s.branch_if_less_than('calculate_difference', time_diff_C_R, THRESHOLD_C + PMTC_BIAS)
    s.add(coin_flag_R,coin_flag_R, 1)

    #calculat pmta, pmtc time diff
    s.calculate_difference = \
    \
    s.branch_if_less_than('decide_init', coin_flag_R, 2)
    s.add(time_delta_R, time_diff_C_R, COINCIDENCE_BIAS)
    s.subtract(time_delta_R,time_delta_R,time_diff_A_R)
    increment_histogram(time_delta_R, 'hist_coin')

    s.branch_if_less_than('check_time_delta', time_delta_R, TIME_WINDOW_UP)
    s.jump('decide_init')

    s.check_time_delta = \
    \
    s.branch_if_less_than('decide_init', time_delta_R, TIME_WINDOW_LOW)

    # Herald: AOMA/AOMC are already OFF; keep AOMB OFF through readout.
    s.herald_analysis = s.set_output_port(
        hd.external_slow_port, [(hd.AOMB_out, 0), (hd.AOMM_out, 0)], 'Herald')
    s.set_output_port(hd.external_control_port,
                      [(hd.MW_A_out, 0), (hd.MW_C_out, 0)], 'Force MW OFF before analysis')
    s.wait_n_clocks(waiting_time_for_AOM_off, 'Wait for AOM extinction')
    if basis == 'mw_detuned':
        emit_mw_events(s, hd.external_control_port, MW_EVENTS)

    # Analyze BEFORE the mechanical wait; ZZ skips MW entirely.
    s.set_output_port(hd.external_slow_port,
                      [(hd.CCD_EC_out, 1), (hd.CCD_EA_out, 0)], 'Fluorescence path')
    wait_for_mirror('wait_flip_mirror')

    # Reference flip-mirror readout: both ions simultaneously, dedicated PMTFA/FC.
    # Both bases read fluorescence with MW gates explicitly OFF.
    detection_outputs = [(hd.AOMA_out, 1), (hd.AOMC_out, 1),
                         (hd.MW_A_out, 0), (hd.MW_C_out, 0)]
    s.detect = s.set_output_port(hd.external_control_port, detection_outputs)
    s.trigger_out([hd.PMTFA_counter_reset, hd.PMTFC_counter_reset])
    s.nop()
    s.set_output_port(hd.counter_control_port,
                      [(hd.PMTFA_counter_enable, 1), (hd.PMTFC_counter_enable, 1)])
    s.wait_n_clocks(TIME_DETECT, 'Fluorescence integration (nominal 100 us)')
    s.set_output_port(hd.counter_control_port,
                      [(hd.PMTFA_counter_enable, 0), (hd.PMTFC_counter_enable, 0)])
    s.read_counter(PMTFA_counter_R, hd.PMTFA_counter_result)
    s.read_counter(PMTFC_counter_R, hd.PMTFC_counter_result)
    s.store_word_to_memory(state_add_R, PMTFA_counter_R)
    s.add(state_add_R, state_add_R, 1)
    s.store_word_to_memory(state_add_R, PMTFC_counter_R)
    s.load_immediate(detect_flag_R, 1)
    s.jump('transfer_statistics')

    # Decide whether we will repeat running
    s.decide_init = \
    \
    s.set_output_port(hd.external_control_port, [(hd.EOM_7GA1_out, 1),(hd.EOM_7GA2_out, 1),(hd.EOM_7GC1_out, 1),(hd.EOM_7GC2_out, 1)], 'Start Cooling')
    s.set_output_port(hd.external_control_port, [(hd.AOMA_out, 1),(hd.AOMC_out, 1)], 'Start Cooling')
    s.wait_n_clocks(waiting_time_for_AOM_off-3, 'Wait for completely turning on the AOM')
    s.load_immediate(AOM_cooling_R, 0) # reg[1] is for the cooling time
    s.load_immediate(coin_flag_R, 0,'reset the flag')
    s.add(wo_cooling_number_R, wo_cooling_number_R, 1, 'run_counter_R++')
    s.branch_if_less_than('init', wo_cooling_number_R, wo_cooling_number)

    s.decide_repeat = \
    \
    s.load_immediate(wo_cooling_number_R, 0) # reg[1] is for the cooling time
    s.add(run_counter_R, run_counter_R, 1, 'run_counter_R++')
    s.branch_if_less_than('cooling', run_counter_R, run_number)
    s.add(outer_loop_R, outer_loop_R, 1, 'run_counter_R++')
    s.load_immediate(run_counter_R, 0,'reset the run counter')
    s.branch_if_less_than('cooling', outer_loop_R, outer_loop_in_fpga)

    # Six words: EA counts, EC counts, group idx, FPGA-loop idx, herald, inner idx.
    # Store counters on BOTH success and exhaustion; all indices are zero-based.
    s.transfer_statistics = s.load_immediate(state_add_R, STATEA_BIAS + 2)
    for value_reg in (run_counter_R, outer_loop_R, detect_flag_R, wo_cooling_number_R):
        s.store_word_to_memory(state_add_R, value_reg)
        s.add(state_add_R, state_add_R, 1)
    s.set_output_port(hd.external_slow_port,
                      [(hd.AOMB_out, 1), (hd.AOMM_out, 1)], 'Cooling after readout')
    s.set_output_port(hd.external_control_port,
                      [(hd.EOM_7GA1_out, 1), (hd.EOM_7GA2_out, 1),
                       (hd.EOM_7GC1_out, 1), (hd.EOM_7GC2_out, 1),
                       (hd.AOMA_out, 1), (hd.AOMC_out, 1)])
    # Mirror returns to collection at NEXT batch start, with full settling wait.
    s.load_immediate(memory_pointer_R, 0, 'memory_pointer_R is used as address pointer and counter')

    s.transfer_repeat = \
    \
    s.load_word_from_memory(transfer1_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.load_word_from_memory(transfer2_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.load_word_from_memory(transfer3_R, memory_pointer_R)
    s.add(memory_pointer_R, memory_pointer_R, 1)
    s.write_to_fifo(transfer1_R, transfer2_R, transfer3_R, 100)
    s.branch_if_less_than('transfer_repeat', memory_pointer_R,  MAX_DATA)

    # Extra protocol row: overflow, version, reserved. Six state words unchanged.
    s.load_immediate(reg[27], 2)
    s.load_immediate(reg[28], 0)
    s.write_to_fifo(reg[26], reg[27], reg[28], 101)
    s.stop()


    return s


def build_program(settings):
    from .config import validate
    c = validate(settings)
    keys = ('basis', 'detuning_hz', 'phase_magnitude_deg', 'groups_per_loop',
            'fpga_loops', 'inner_trials', 'detection_us', 'cooling_us',
            'initialization_us', 'decay_lower_a', 'decay_lower_c',
            'coincidence_half_window_bins', 'aom_off_us', 'stopwatch_wait_us')
    return build_sequence(**{k:c[k] for k in keys},
        half_pi_ea_us=c['pi_ea_us']/2, half_pi_ec_us=c['pi_ec_us']/2,
        mirror_wait_repeats=round(c['mirror_wait_ms']*2))
