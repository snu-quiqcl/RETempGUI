"""네 개 스캔 동시 시작. 실제 모터가 절대 좌표 5990–6010 µm로 이동합니다."""
def main(devices):
    fpga = devices.fpga('fpga_local')
    pairs = [('EA_px', 'EA_py'), ('EC_px', 'EC_py'),
             ('EC_sx', 'EC_sy'), ('EA_sx', 'EA_sy')]
    handles = []
    for scan, (x_name, y_name) in enumerate(pairs, 1):
        handles.append(fpga.start_scan(
            devices.motor(x_name), devices.motor(y_name), settings={
                'scan': scan, 'pmt': scan - 1,
                'x_start_um': 5990, 'x_stop_um': 6010, 'x_step_um': 1,
                'y_start_um': 5990, 'y_stop_um': 6010, 'y_step_um': 1,
                'exposure_ms': 100, 'average': 1, 'settle_ms': 1,
                'directory': 'logs/fiber_scan',
            }))
    # 시작은 네 개 모두 먼저, 결과는 각자의 핸들에서 받습니다.
    # 같은 workflow이므로 오류/Cancel은 전체 Scan에 적용됩니다.
    for scan, handle in enumerate(handles, 1):
        result = handle.wait()
        print('Scan', scan, result['status'], result['folder'])
