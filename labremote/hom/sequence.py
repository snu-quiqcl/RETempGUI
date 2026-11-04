"""HOM v2_07 timing, with per-trial AOM OFF, SYNC accounting and saturation flag.

FIFO: 4*M words (A, C, HOM), tag 100; 48-bit valid/missing counters tags
101/102 (least significant word first); tag 103 = overflow, protocol version, 0.
No individual event records and no host-side chunk splitting.
"""
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram, reg
from .config import validate,hardware,outputs,auxiliary

def build_program(settings):
    c=validate(settings);h=hardware(c);m=c['MAX_TIME_DIFFERENCE'];s=SequencerProgram()
    for i in range(32):s.load_immediate(reg[i],0)
    s.clear_memory=s.store_word_to_memory(reg[10],reg[11])
    s.add(reg[10],reg[10],1);s.branch_if_less_than('clear_memory',reg[10],4*m)
    auxiliary(s,c,True)
    s.repeat=s.load_immediate(reg[8],0)
    outputs(s,c,{'AOMA':1,'AOMC':1})
    s.wait_n_clocks(c['TIME_1US']-5)
    # The inner-loop destination includes OFF and its settling delay.
    s.trial=outputs(s,c,{'AOMA':0,'AOMC':0})
    s.wait_n_clocks(c['waiting_time_for_AOM_off']-3)
    outputs(s,c,{'TRIG':1});outputs(s,c,{'TRIG':0})
    s.trigger_out([h.PMTA_stopwatch_reset,h.PMTC_stopwatch_reset,h.SYNC_stopwatch_reset])
    s.nop()
    s.trigger_out([h.PMTA_stopwatch_start,h.PMTC_stopwatch_start,h.SYNC_stopwatch_start])
    s.wait_n_clocks(c['waiting_time_for_stopwatch']-3)
    s.read_counter(reg[2],h.Trigger_level)
    s.read_counter(reg[3],h.SYNC_stopwatch_result)
    s.read_counter(reg[4],h.PMTA_stopwatch_result)
    s.read_counter(reg[5],h.PMTC_stopwatch_result)
    outputs(s,c,{'AOMA':1,'AOMC':1})  # Cool during all arithmetic and branching.
    s.branch_if_equal_with_mask('missing_sync',reg[2],0,1<<h.SYNC_stopwatch_stopped_TLI)

    def count48(base,label):
        s.add(reg[base],reg[base],1)
        s.branch_if_less_than(label+'_carry1',reg[base],1);s.jump(label+'_done')
        setattr(s,label+'_carry1',s.add(reg[base+1],reg[base+1],1))
        s.branch_if_less_than(label+'_carry2',reg[base+1],1);s.jump(label+'_done')
        setattr(s,label+'_carry2',s.add(reg[base+2],reg[base+2],1))
        setattr(s,label+'_done',s.nop())

    def increment(address,label):
        s.load_word_from_memory(reg[11],address)
        s.branch_if_less_than(label+'_inc',reg[11],65535)
        s.load_immediate(reg[26],1);s.jump(label+'_done')
        setattr(s,label+'_inc',s.add(reg[11],reg[11],1))
        s.store_word_to_memory(address,reg[11])
        setattr(s,label+'_done',s.nop())

    count48(20,'valid')
    s.branch_if_equal_with_mask('check_c',reg[2],0,1<<h.PMTA_stopwatch_stopped_TLI)
    s.subtract(reg[6],reg[4],reg[3])
    s.branch_if_less_than('a_in_range',reg[6],m);s.jump('check_c')
    s.a_in_range=s.branch_if_less_than('check_c',reg[6],c['THRESHOLD_A'])
    increment(reg[6],'a');s.add(reg[9],reg[9],1)
    s.check_c=s.branch_if_equal_with_mask('decide_repeat',reg[2],0,1<<h.PMTC_stopwatch_stopped_TLI)
    s.subtract(reg[7],reg[5],reg[3])
    s.branch_if_less_than('c_in_range',reg[7],m);s.jump('decide_repeat')
    s.c_in_range=s.branch_if_less_than('decide_repeat',reg[7],c['THRESHOLD_C'])
    s.add(reg[18],reg[7],m)
    increment(reg[18],'c');s.add(reg[9],reg[9],1)
    s.branch_if_less_than('decide_repeat',reg[9],2)
    s.add(reg[15],reg[7],3*m);s.subtract(reg[15],reg[15],reg[6])
    increment(reg[15],'hom');s.jump('decide_repeat')
    s.missing_sync=s.nop();count48(23,'missing')
    s.decide_repeat=s.load_immediate(reg[9],0)
    s.add(reg[8],reg[8],1);s.branch_if_less_than('trial',reg[8],c['inner_loop_number'])
    s.add(reg[0],reg[0],1);s.branch_if_less_than('repeat',reg[0],c['run_number'])
    s.add(reg[16],reg[16],1);s.load_immediate(reg[0],0)
    s.branch_if_less_than('repeat',reg[16],c['outer_loop_in_fpga'])
    s.load_immediate(reg[10],0)
    s.transfer=s.load_word_from_memory(reg[12],reg[10]);s.add(reg[10],reg[10],1)
    s.load_word_from_memory(reg[13],reg[10]);s.add(reg[10],reg[10],1)
    s.load_word_from_memory(reg[14],reg[10]);s.add(reg[10],reg[10],1)
    s.write_to_fifo(reg[12],reg[13],reg[14],100)
    s.branch_if_less_than('transfer',reg[10],4*m)
    s.write_to_fifo(reg[20],reg[21],reg[22],101)
    s.write_to_fifo(reg[23],reg[24],reg[25],102)
    s.load_immediate(reg[27],1);s.load_immediate(reg[28],0)
    s.write_to_fifo(reg[26],reg[27],reg[28],103)
    s.stop()
    return s
