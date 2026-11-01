"""Run EA then EC on the same connected FPGA; local JSON settings/mapping apply."""


def main(devices):
    fpga=devices.fpga('fpga_local')
    ea=fpga.run_fluorescence('EA').wait()
    ec=fpga.run_fluorescence('EC').wait()
    print('EA:',ea['folder'],ea['summary'])
    print('EC:',ec['folder'],ec['summary'])
