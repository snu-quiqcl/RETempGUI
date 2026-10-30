"""FPGA와 EA px/py를 연결한 뒤 실행. 실제 모터를 절대 좌표 5990–6010 µm에서 이동합니다."""
def main(devices):
    fpga = devices.fpga('fpga_local')
    x = devices.motor('EA_px')
    y = devices.motor('EA_py')
    result = fpga.start_scan(x, y, settings={
        'pmt': 0,
        'x_start_um': 5990, 'x_stop_um': 6010, 'x_step_um': 1,
        'y_start_um': 5990, 'y_stop_um': 6010, 'y_step_um': 1,
        'x_um_per_unit': 1000, 'y_um_per_unit': 1000,
        'exposure_ms': 1, 'average': 10, 'settle_ms': 100,
        'directory': 'logs/fiber_scan',
    }).wait()
    print('Scan result:', result['status'], result['folder'])
