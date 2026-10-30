"""EA BNC를 0.05 Vpp로 설정하고 오실로 측정 조건 충족 시 0.16 Vpp로 올립니다.

두 장비를 먼저 Connect한 뒤 실행하세요. BNC RF 출력을 켜며 이미 켜져 있으면 유지합니다.
CH1/CH2 Vpp는 순차적으로 한 번씩 읽으며, 조건 미충족 시 0.05 Vpp를 유지합니다.
"""


def main(devices):
    sg_EA = devices.sg384('sg384_EA', port='BNC')
    scope_EA = devices.ds1052e('ds1052e_EA')
    sg_EC = devices.sg384('sg384_EA', port='BNC')
    scope_EA = devices.ds1052e('ds1052e_EA')

    sg.on().wait()
    sg.set_power(0.05, unit='Vpp').wait()

    ch1_vpp = scope.acquire('ch1_vpp').wait()
    ch2_vpp = scope.acquire('ch2_vpp').wait()

    if ch1_vpp is None or ch2_vpp is None:
        raise RuntimeError('오실로 Vpp 측정값을 얻지 못했습니다.')

    if ch1_vpp >= 0.2 and ch2_vpp <= 0.01:
        sg.set_power(0.16, unit='Vpp').wait()
    else:
        raise RuntimeError('check amp or connection')