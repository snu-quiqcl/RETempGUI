"""RE without flip mirror, using one frozen Queue settings snapshot."""
WORKFLOW_UI = {'editor':'entanglement_no_mirror'}

def main(devices):
    p=devices.parameters
    if not p.get('fpga') or not p.get('settings'):
        raise ValueError('RE without flip mirror requires FPGA and frozen settings')
    return devices.fpga(p['fpga']).run_entanglement_no_mirror(
        settings=p['settings'],directory=devices.run_directory).wait()
