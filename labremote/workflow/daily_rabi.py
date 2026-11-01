"""Connect fpga_local and apsyn420_mw; settings/roles come from each experiment JSON."""
def main(devices):
    fpga=devices.fpga('fpga_local')
    microwave=devices.anapico('apsyn420_mw')
    for chamber in ('EA','EC'):
        result=fpga.run_rabi(chamber,microwave).wait()
        print(chamber,result['status'],result['folder'])
