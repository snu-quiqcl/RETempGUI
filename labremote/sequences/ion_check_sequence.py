"""One B/A/C acquisition; FIFO = [A count, B count, C count, 0x10].

Counts are PMTA + PMTC after the NPBS. Keep their sum below 65536.
Normal completion leaves A/C and both 7G pairs on, B/2G/MW off.
Cancellation/error output recovery belongs to the caller, not this builder.
"""
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram, reg
from labremote.devices.fpga.vendor import HardwareDefinition_remote_ent_test_ec as hd


def build_program(parameters):
    exposure_us = parameters.get('exposure_us', 1000)
    settle_us = parameters.get('settle_us', 100)
    for name, value in (('exposure_us', exposure_us), ('settle_us', settle_us)):
        if type(value) is not int or not 1 <= value <= 10000:
            raise ValueError(f'{name} must be an integer in 1..10000')
    s = SequencerProgram()
    count_a, count_b, count_c, pmt_a, pmt_c = reg[:5]

    def wait_us(duration):
        remaining = duration * 100  # 10 ns clock; wait instruction adds 2 clocks.
        while remaining:
            chunk = min(remaining, 60000)
            s.wait_n_clocks(chunk - 2)
            remaining -= chunk

    def counters(enabled):
        s.set_output_port(hd.counter_control_port, [
            (hd.PMTA_counter_enable, enabled), (hd.PMTC_counter_enable, enabled)])

    def lasers(a=0, b=0, c=0):
        s.set_output_port(hd.external_slow_port, [(hd.AOMB_out, 0)])
        s.set_output_port(hd.external_control_port, [
            (hd.AOMA_out, a), (hd.AOMC_out, c),
            (hd.EOM_7GA1_out, a), (hd.EOM_7GA2_out, a),
            (hd.EOM_7GC1_out, c), (hd.EOM_7GC2_out, c),
            (hd.EOM_2GA_out, 0), (hd.EOM_2GC_out, 0),
            (hd.MW_A_out, 0), (hd.MW_C_out, 0)])
        if b:
            s.set_output_port(hd.external_slow_port, [(hd.AOMB_out, 1)])

    def measure(a, b, c, destination):
        lasers(a, b, c)
        wait_us(settle_us)
        s.trigger_out([hd.PMTA_counter_reset, hd.PMTC_counter_reset])
        counters(1)
        wait_us(exposure_us)
        counters(0)
        s.read_counter(pmt_a, hd.PMTA_counter_result)
        s.read_counter(pmt_c, hd.PMTC_counter_result)
        s.add(destination, pmt_a, pmt_c)

    counters(0)
    measure(0, 1, 0, count_b)
    measure(1, 0, 0, count_a)
    measure(0, 0, 1, count_c)
    lasers(a=1, c=1)
    s.write_to_fifo(count_a, count_b, count_c, 0x10)
    s.stop()
    return s
