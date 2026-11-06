"""Bounded RF reference/photon acquisition; never writes external light outputs."""
import math
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram, reg
from .config import hd, PINS, bins


def correlation(c, target):
    if not 1 <= target <= 30000:
        raise ValueError('FPGA accepted-event batch must be 1..30000')
    trg, pmt = PINS[c['trg_pin']], PINS[c['pmt_pin']]
    get = lambda name, suffix: getattr(hd, name+'_'+suffix)
    size=bins(c); s=SequencerProgram()
    s.load_immediate(reg[10],0);s.load_immediate(reg[11],0)
    s.clear=s.store_word_to_memory(reg[10],reg[11])
    s.add(reg[10],reg[10],1);s.branch_if_less_than('clear',reg[10],size)
    for i in (0,1,2):s.load_immediate(reg[i],0)  # accepted, attempts low/high
    s.trial=s.trigger_out([get(trg,'stopwatch_reset'),get(pmt,'stopwatch_reset')])
    s.nop();s.trigger_out([get(trg,'stopwatch_start'),get(pmt,'stopwatch_start')])
    wait=math.ceil((1000/c['rf_mhz']+size*1.25)/10)+2
    s.wait_n_clocks(wait)
    s.read_counter(reg[3],hd.Trigger_level)
    s.read_counter(reg[4],get(trg,'stopwatch_result'))
    s.read_counter(reg[5],get(pmt,'stopwatch_result'))
    mask=(1<<get(trg,'stopwatch_stopped_TLI'))|(1<<get(pmt,'stopwatch_stopped_TLI'))
    s.branch_if_equal_with_mask('both',reg[3],mask,mask);s.jump('next_trial')
    s.both=s.branch_if_less_than('lag',reg[4],reg[5]);s.jump('next_trial')
    s.lag=s.subtract(reg[6],reg[5],reg[4])
    # Physically valid window; padding bins are transferred but never filled.
    window=math.ceil(1000*c['periods']/c['rf_mhz']/1.25)
    s.branch_if_less_than('accept',reg[6],window);s.jump('next_trial')
    s.accept=s.load_word_from_memory(reg[11],reg[6])
    s.add(reg[11],reg[11],1);s.store_word_to_memory(reg[6],reg[11]);s.add(reg[0],reg[0],1)
    s.next_trial=s.add(reg[1],reg[1],1)
    s.branch_if_equal('carry',reg[1],0);s.jump('decide')
    s.carry=s.add(reg[2],reg[2],1)
    s.decide=s.branch_if_less_than('budget',reg[0],target);s.jump('transfer')
    s.budget=s.branch_if_less_than('trial',reg[2],100)  # <= 6,553,600 attempts
    s.transfer=s.load_immediate(reg[10],0)
    s.transfer_loop=s.load_word_from_memory(reg[11],reg[10]);s.add(reg[10],reg[10],1)
    s.load_word_from_memory(reg[12],reg[10]);s.add(reg[10],reg[10],1)
    s.load_word_from_memory(reg[13],reg[10]);s.add(reg[10],reg[10],1)
    s.write_to_fifo(reg[11],reg[12],reg[13],100)
    s.branch_if_less_than('transfer_loop',reg[10],size)
    s.write_to_fifo(reg[0],reg[1],reg[2],101);s.stop()
    return s


def rf_test(c):
    name=PINS[c['counter_pin']];s=SequencerProgram()
    s.load_immediate(reg[0],0)
    s.repeat=s.trigger_out([getattr(hd,name+'_counter_reset')]);s.nop()
    s.set_output_port(hd.counter_control_port,[(getattr(hd,name+'_counter_enable'),1)])
    # wait consumes n+2 cycles, disable instruction consumes the final cycle.
    ticks=round(c['gate_us']*100)
    s.wait_n_clocks(ticks-3)
    s.set_output_port(hd.counter_control_port,[(getattr(hd,name+'_counter_enable'),0)])
    s.read_counter(reg[1],getattr(hd,name+'_counter_result'))
    s.write_to_fifo(reg[0],reg[1],reg[1],10);s.add(reg[0],reg[0],1)
    s.branch_if_less_than('repeat',reg[0],c['rf_repeats']);s.stop()
    return s
