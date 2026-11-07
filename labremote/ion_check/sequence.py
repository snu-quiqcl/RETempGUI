"""One B/A/C acquisition; FIFO = [A count, B count, C count, 0x10].

Counts are the sum of selected PMT inputs. Keep their sum below 65536.
Normal completion leaves A/C and both 7G pairs on, B/2G/MW off.
Cancellation/error output recovery belongs to the caller, not this builder.
"""
from labremote.devices.fpga.vendor.SequencerProgram_v1_08 import SequencerProgram, reg
from labremote.devices.fpga.vendor import HardwareDefinition_remote_ent_test_ec as hd
from labremote.devices.fpga.controller import OUTPUTS
from labremote.ion_check.config import default_mapping,validate_mapping,pmt_names,output_levels


def build_program(parameters):
    c={'mapping':validate_mapping(parameters.get('mapping',default_mapping()))}
    inputs=pmt_names(c)
    exposure_us = parameters.get('exposure_us', 1000)
    settle_us = parameters.get('settle_us', 100)
    for name, value in (('exposure_us', exposure_us), ('settle_us', settle_us)):
        if type(value) is not int or not 1 <= value <= 10000:
            raise ValueError(f'{name} must be an integer in 1..10000')
    s = SequencerProgram()
    count_a, count_b, count_c, pmt_a, pmt_c = reg[:5]
    overflow = reg[5]
    s.load_immediate(overflow, 0)

    def wait_us(duration):
        remaining = duration * 100  # 10 ns clock; wait instruction adds 2 clocks.
        while remaining:
            chunk = min(remaining, 60000)
            s.wait_n_clocks(chunk - 2)
            remaining -= chunk

    def counters(enabled):
        s.set_output_port(hd.counter_control_port,[(getattr(hd,name+'_counter_enable'),enabled) for name in inputs])

    def lasers(a=0, b=0, c=0):
        mapping=validate_mapping(parameters.get('mapping',default_mapping()))
        # Break before make, including when a role is assigned to the slow port.
        for levels in ({mapping['laser_'+key]:0 for key in 'abc'},output_levels({'mapping':mapping},a,b,c)):
            ports={}
            for name,value in levels.items():
                _,port,bit=OUTPUTS[name];ports.setdefault(port,[]).append((bit,value))
            for port,values in sorted(ports.items()):s.set_output_port(port,values)

    def measure(a, b, c, destination):
        lasers(a, b, c)
        wait_us(settle_us)
        s.trigger_out([getattr(hd,name+'_counter_reset') for name in inputs])
        counters(1)
        wait_us(exposure_us)
        counters(0)
        s.read_counter(pmt_a,getattr(hd,inputs[0]+'_counter_result'))
        if len(inputs)==2:s.read_counter(pmt_c,getattr(hd,inputs[1]+'_counter_result'))
        else:s.load_immediate(pmt_c,0)
        s.add(destination, pmt_a, pmt_c)
        label = 'overflow_' + destination
        done = 'sum_done_' + destination
        s.branch_if_less_than(label, destination, pmt_a)
        s.jump(done)
        setattr(s, label, s.load_immediate(overflow, 1))
        setattr(s, done, s.nop())

    counters(0)
    measure(0, 1, 0, count_b)
    measure(1, 0, 0, count_a)
    measure(0, 0, 1, count_c)
    lasers(a=1, c=1)
    s.branch_if_equal('overflow_result', overflow, 1)
    s.write_to_fifo(count_a, count_b, count_c, 0x10)
    s.stop()
    s.overflow_result = s.write_to_fifo(count_a, count_b, count_c, 0x11)
    s.stop()
    return s
