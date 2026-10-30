"""Connect the device in its tab before running this workflow."""


def main(devices):
    fpga = devices.fpga('fpga_local')
    result = fpga.measure(channel=0, exposure_ms=100).wait()
    print('PMT count:', result['count'])
    # fpga.set_output('AOMC', True).wait()
