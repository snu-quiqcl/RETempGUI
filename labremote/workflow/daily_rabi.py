"""Set microwave frequency/output externally first. This example performs one fixed-MW Rabi operation."""
def main(devices):
    result=devices.fpga('fpga_local').run_rabi('EA').wait()
    print(result['status'],result['folder'])
