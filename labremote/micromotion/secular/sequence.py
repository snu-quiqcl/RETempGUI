"""Original bounded phase-bin sequence; external cooling/light outputs untouched."""
import math
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram, reg
from labremote.devices.fpga.mapping import hd
from .model import _geometry, CORRELATION_LABEL, COUNT_LABEL

def _build_correlation(params, hardware, frequency_khz, attempts, target):
    """One bounded FPGA block, at most 60000 increments per histogram word."""
    attempts, target = int(attempts), int(target)
    if not 1 <= target <= attempts <= 60000:
        raise ValueError("FPGA block requires 1 <= target <= attempts <= 60000.")
    bins = int(params["phase_bins"])
    end,_,_,_ = _geometry(frequency_khz,bins)
    words = ((bins+2)//3)*3
    base, remainder = divmod(end,bins)
    sw = hardware["pmts"][0]["timing"]
    sy = hardware["signals"]["modulation_sync"]
    s = SequencerProgram()
    s.load_immediate(reg[11],0)
    s.load_immediate(reg[10],0)
    s.clear_memory = s.store_word_to_memory(reg[10],reg[11])
    s.add(reg[10],reg[10],1)
    s.branch_if_less_than("clear_memory",reg[10],words)
    s.load_immediate(reg[0],0,"actual attempts")
    s.load_immediate(reg[1],0,"accepted events")
    s.attempt = s.add(reg[0],reg[0],1,"count every attempt, including final success")
    s.trigger_out([sw["reset"],sy["reset"]])
    s.nop()
    s.trigger_out([sw["start"],sy["start"]])
    # Cover first Sync (<=T) followed by a full accepted period (<=T).
    s.wait_n_clocks(int(math.ceil(2*end/8))-3)
    s.read_counter(reg[2],sw["trigger_level"])
    s.read_counter(reg[3],sy["result"])
    s.read_counter(reg[4],sw["result"])
    mask = (1<<sw["stopped_tli"]) | (1<<sy["stopped_tli"])
    s.branch_if_equal_with_mask("check_order",reg[2],mask,mask)
    s.jump("next_attempt")
    s.check_order = s.branch_if_less_than("difference",reg[3],reg[4])
    s.jump("next_attempt")
    s.difference = s.subtract(reg[5],reg[4],reg[3])
    s.branch_if_less_than("bin_start",reg[5],end)
    s.jump("next_attempt")
    # Bresenham bin widths: floor((j+1)*end/bins)-floor(j*end/bins).
    # Uses no multiply/divide instruction; every bin has positive exposure.
    s.bin_start = s.load_immediate(reg[6],0,"bin index")
    s.load_immediate(reg[7],0,"bin-width fractional accumulator")
    s.bin_loop = s.load_immediate(reg[8],base)
    s.add(reg[7],reg[7],remainder)
    s.branch_if_less_than("compare_width",reg[7],bins)
    s.subtract(reg[7],reg[7],bins)
    s.add(reg[8],reg[8],1)
    s.compare_width = s.branch_if_less_than("store_event",reg[5],reg[8])
    s.subtract(reg[5],reg[5],reg[8])
    s.add(reg[6],reg[6],1)
    s.jump("bin_loop")
    s.store_event = s.load_word_from_memory(reg[11],reg[6])
    s.add(reg[11],reg[11],1)
    s.store_word_to_memory(reg[6],reg[11])
    s.add(reg[1],reg[1],1)
    s.branch_if_less_than("next_attempt",reg[1],target)
    s.jump("transfer")
    s.next_attempt = s.branch_if_less_than("attempt",reg[0],attempts)
    s.transfer = s.load_immediate(reg[10],0)
    s.transfer_loop = s.load_word_from_memory(reg[11],reg[10])
    s.add(reg[10],reg[10],1)
    s.load_word_from_memory(reg[12],reg[10])
    s.add(reg[10],reg[10],1)
    s.load_word_from_memory(reg[13],reg[10])
    s.add(reg[10],reg[10],1)
    s.write_to_fifo(reg[11],reg[12],reg[13],CORRELATION_LABEL)
    s.branch_if_less_than("transfer_loop",reg[10],words)
    s.load_immediate(reg[9],bins)
    s.write_to_fifo(reg[0],reg[1],reg[9],CORRELATION_LABEL,"attempts, events, bins")
    s.stop()
    return s


def _build_count(params,hardware):
    """One exposure, split into <=100 us gates; stream each segment count.

    Enable at t0, WAIT(n) next cycle takes n+3 clocks, disable follows:
    live interval = n+4 clocks. Thus n=100*segment_us-4.
    """
    exposure = int(params["count_rate_exposure_time_us"])
    full,tail = divmod(exposure,100)
    c = hardware["pmts"][0]["count"]
    s=SequencerProgram()
    s.set_output_port(c["control_port"],[(c["enable"],0)])
    s.load_immediate(reg[2],0,"segment index")
    def gate(us,label=None):
        instruction=s.trigger_out([c["reset"]])
        if label:
            setattr(s,label,instruction)
        s.nop()
        s.set_output_port(c["control_port"],[(c["enable"],1)])
        s.wait_n_clocks(us*100-4)
        s.set_output_port(c["control_port"],[(c["enable"],0)])
        s.nop()
        s.read_counter(reg[0],c["result"])
        s.load_immediate(reg[1],us*100)
        s.write_to_fifo(reg[0],reg[1],reg[2],COUNT_LABEL)
        s.add(reg[2],reg[2],1)
    if full:
        gate(100,"segment")
        s.branch_if_less_than("segment",reg[2],full)
    if tail:
        gate(tail)
    s.stop()
    return s
