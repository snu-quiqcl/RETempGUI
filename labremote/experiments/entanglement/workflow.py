"""RE with flip mirror; the standalone experiment API and frozen settings."""
WORKFLOW_UI = {'editor': 'entanglement'}

def main(devices):
    p=devices.parameters
    if not p.get('fpga') or not p.get('settings'):
        raise ValueError('RE with flip mirror requires FPGA and frozen settings')
    return devices.fpga(p['fpga']).run_entanglement(
        settings=p['settings'],directory=devices.run_directory or p.get('directory')).wait()
