"""Queue parameters: chamber EA/EC, optional fpga/settings_file/settings.

Microwave frequency and output remain under external workflow/manual control.
"""
def main(devices):
    from pathlib import Path
    p=devices.parameters
    directory=str(Path(devices.run_directory)/'rabi') if devices.run_directory else None
    result=devices.fpga(p.get('fpga','fpga_local')).run_rabi(
        p.get('chamber','EA'),settings=p.get('settings'),
        settings_file=p.get('settings_file'),directory=directory).wait()
    return {'status':result['status'],'result_paths':[result['folder']]}
