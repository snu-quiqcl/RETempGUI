# -*- coding: utf-8 -*-
"""
Created on Thu Feb  1 21:08:57 2018

@author: IonTrap
"""

# mux2 #(16) external_control(.d0(output_ports[0]), .d1(patterns[17:32]), .select(manual_control_on), .y(external_output));
# assign monitoring_32bits = {external_output, stopped, manual_control_on, {(14-INSTRUCTION_MEMORY_ADDR_WIDTH){1'b0}}, PC[INSTRUCTION_MEMORY_ADDR_WIDTH-1:0]};

HW_VERSION = 'Seq v4_05'

#%%################################################################
# Input connections to sequencer
###################################################################

####################################################
# Input counter port assignment
jb_0_counter_result = 0     # assign counters_13_0[0] = jb_0_counter_output;
jb_2_counter_result = 1     # assign counters_13_0[1] = jb_2_counter_output;
jb_4_counter_result = 2     # assign counters_13_0[2] = jb_4_counter_output;
jb_6_counter_result = 3     # assign counters_13_0[3] = jb_6_counter_output;

jb_0_stopwatch_result = 6   # assign counters_13_0[6] = jb_0_stopwatch_output;
jb_2_stopwatch_result = 7   # assign counters_13_0[7] = jb_2_stopwatch_output;
ja_4_stopwatch_result = 8   # assign counters_13_0[8] = ja_4_stopwatch_output;
ja_6_stopwatch_result = 9   # assign counters_13_0[9] = ja_6_stopwatch_output;
ja_2_stopwatch_result = 10 # assign counters_13_0[10] = ja_2_stopwatch_output; // ja_2 will be used for pulse picker trigger
jb_4_stopwatch_result = 11
jb_6_stopwatch_result = 12
ja_6_counter_result = 13  # replaces sequencer patterns[1:16] readback

Trigger_level = 14                  # Fixed internally inside sequencer
Remaining_counts_from_wait = 15     # Fixed internally inside sequencer



####################################################
# Trigger_level_in bit assignment
jb_0_stopwatch_stopped_TLI = 15    # assign trigger_level_in[15] = jb_0_stopwatch_stopped;
jb_2_stopwatch_stopped_TLI = 14    # assign trigger_level_in[14] = jb_2_stopwatch_stopped;
ja_4_stopwatch_stopped_TLI = 13    # assign trigger_level_in[13] = ja_4_stopwatch_stopped;
ja_6_stopwatch_stopped_TLI = 12    # assign trigger_level_in[12] = ja_6_stopwatch_stopped;
ja_2_stopwatch_stopped_TLI = 11   # assign trigger_level_in[11] = ja_2_stopwatch_stopped;



#%%################################################################
# Output connections from sequencer
###################################################################

####################################################
# Pulse trigger_out assignment
jb_0_counter_reset = 6  # shared with same-pin stopwatch reset
jb_2_counter_reset = 5  # shared with same-pin stopwatch reset
jb_4_counter_reset = 13     # assign jb_4_counter_reset = trigger_out[13];
jb_6_counter_reset = 12     # assign jb_6_counter_reset = trigger_out[12];

jb_0_stopwatch_start = 11   # assign jb_0_stopwatch_start = trigger_out[11];
jb_2_stopwatch_start = 10   # assign jb_2_stopwatch_start = trigger_out[10];
ja_4_stopwatch_start =  9   # assign ja_4_stopwatch_start = trigger_out[9];
ja_6_stopwatch_start =  8   # assign ja_6_stopwatch_start = trigger_out[8];
ja_2_stopwatch_start = 7    # assign ja_2_stopwatch_start = trigger_out[7];

jb_0_stopwatch_reset = 6    # assign jb_0_stopwatch_reset = trigger_out[6];
jb_2_stopwatch_reset = 5    # assign jb_2_stopwatch_reset = trigger_out[5];
ja_4_stopwatch_reset = 4    # assign ja_4_stopwatch_reset = trigger_out[4];
ja_6_stopwatch_reset = 3    # assign ja_6_stopwatch_reset = trigger_out[3];
ja_2_stopwatch_reset = 2    # assign ja_2_stopwatch_reset = trigger_out[2];


####################################################
# Output port[0] bit assignment
external_control_port = 0
ja_3_out = 15       # assign ja_3 = external_output[15]; // output_ports[0][15] or patterns[17]
ja_7_out = 14       # assign ja_7 = external_output[14]; // output_ports[0][14] or patterns[18]
jb_1_out = 13       # assign jb_1 = external_output[13]; // output_ports[0][13] or patterns[19]
jb_3_out = 12       # assign jb_3 = external_output[12]; // output_ports[0][12] or patterns[20]
jb_5_out = 11       # assign jb_5 = external_output[11]; // output_ports[0][11] or patterns[21]
jb_7_out = 10       # assign jb_7 = external_output[10]; // output_ports[0][10] or patterns[22]
ja_0_out = 9        # assign ja_0 = external_output[9]; // output_ports[0][9] or patterns[23]
ja_1_out = 8        # assign ja_1 = external_output[8]; // output_ports[0][8] or patterns[24]
ja_5_out = 6        # assign ja_5 = external_output[6]; // output_ports[0][6] or patterns[26]

####################################################
# Output port[1] bit assignment
counter_control_port = 1
jb_0_counter_enable = 15      # assign jb_0_counter_clock_enable = output_ports_1[15];
jb_2_counter_enable = 14      # assign jb_2_counter_clock_enable = output_ports_1[14];
jb_4_counter_enable = 13      # assign jb_4_counter_clock_enable = output_ports_1[13];
jb_6_counter_enable = 12      # assign jb_6_counter_clock_enable = output_ports_1[12];


####################################################
# Output port[2] is assigned to slow output port
external_slow_port = 2
jd_7_out = 15		# assign jd_7 = output_ports_2[15];
jd_6_out = 14		# assign jd_6 = output_ports_2[14];
jd_5_out = 13		# assign jd_5 = output_ports_2[13];
jd_4_out = 12		# assign jd_4 = output_ports_2[12];
jd_3_out = 11		# assign jd_3 = output_ports_2[11];
jd_2_out = 10		# assign jd_2 = output_ports_2[10];
jd_1_out = 9		# assign jd_1 = output_ports_2[9];
jd_0_out = 8		# assign jd_0 = output_ports_2[8];
jc_7_out = 7		# assign jc_7 = output_ports_2[7];
jc_6_out = 6		# assign jc_6 = output_ports_2[6];
jc_5_out = 5		# assign jc_5 = output_ports_2[5];
jc_4_out = 4		# assign jc_4 = output_ports_2[4];
jc_3_out = 3		# assign jc_3 = output_ports_2[3];
jc_2_out = 2		# assign jc_2 = output_ports_2[2];
jc_1_out = 1		# assign jc_1 = output_ports_2[1];
jc_0_out = 0		# assign jc_0 = output_ports_2[0];

#%%################################################################
# Monitoring pins assignment
###################################################################

#assign monitoring_32bits = {external_output, stopped, manual_control_on, {(14-INSTRUCTION_MEMORY_ADDR_WIDTH){1'b0}}, PC[INSTRUCTION_MEMORY_ADDR_WIDTH-1:0]};

# Existing FPGA ja_2 counter, now explicitly represented in this definition.
ja_2_counter_result = 4
ja_2_counter_reset = 2  # shared with same-pin stopwatch reset
ja_2_counter_enable = 11

# v4_05r2 additions. All seven input pins support both functions.
ja_4_counter_result = 5
ja_4_counter_enable = 10
ja_6_counter_enable = 9
ja_4_counter_reset = ja_4_stopwatch_reset
ja_6_counter_reset = ja_6_stopwatch_reset
jb_4_stopwatch_reset = jb_4_counter_reset
jb_6_stopwatch_reset = jb_6_counter_reset
jb_4_stopwatch_start = 15
jb_6_stopwatch_start = 14
jb_4_stopwatch_stopped_TLI = 10
jb_6_stopwatch_stopped_TLI = 9
COUNTER_PINS = ('jb_0', 'jb_2', 'jb_4', 'jb_6', 'ja_2', 'ja_4', 'ja_6')
STOPWATCH_PINS = COUNTER_PINS
# Output port 0 bits 7 and 5 remain reserved/unconnected (ja_4/ja_6 are inputs).
