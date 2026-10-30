"""EA px/py/pz 절대 좌표 XYZ 스캔. 실제 장비가 이동하므로 범위를 확인하세요."""
def main(devices):
    fpga = devices.fpga('fpga_local')
    result = fpga.start_scan(
        devices.motor('EA_px'), devices.motor('EA_py'),
        settings={
            'scan': 1, 'pmt': 0,
            'x_start_um': 5990, 'x_stop_um': 6010, 'x_step_um': 2,
            'y_start_um': 5990, 'y_stop_um': 6010, 'y_step_um': 2,
            'z_start_um': 5999, 'z_stop_um': 6001, 'z_step_um': 1,
            'exposure_ms': 100, 'average': 1, 'settle_ms': 1,
            'directory': 'logs/fiber_scan',
        }, z_motor=devices.motor('EA_pz'),
    ).wait()
    for plane in result['z_fits']:
        print('Z (µm):', plane['z_um'], 'fit:', plane['fit'])
