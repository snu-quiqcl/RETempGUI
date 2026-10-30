"""EA/EC 증폭 조건을 확인한 뒤 SG384, Windfreak, DDS 출력을 설정합니다.

사용할 장비를 UI에서 먼저 Connect하세요. Windfreak CH1/CH2는 A/B입니다.
두 오실로 조건을 모두 통과해야 SG 목표 파워와 나머지 RF 설정을 적용합니다.
실패/취소 시 자동 OFF나 원상 복구는 하지 않으며, 완료된 설정은 유지됩니다.
"""


def main(devices):
    sg_ea = devices.sg384('sg384_EA', port='BNC')
    sg_ec = devices.sg384('sg384_EC', port='BNC')
    scope_ea = devices.ds1052e('ds1052e_EA')
    scope_ec = devices.ds1052e('ds1052e_EC')
    wf_760 = devices.windfreak('synthhd_760', channel='A')
    wf_2g_ch1 = devices.windfreak('synthhd_2g', channel='A')
    wf_2g_ch2 = devices.windfreak('synthhd_2g', channel='B')
    wf_3g = devices.windfreak('synthhd_3g', channel='A')
    anapico = devices.anapico('apsyn420_7g')
    dds_ch1 = devices.dds('dds4', channel=1)
    dds_ch3 = devices.dds('dds4', channel=3)

    # ON은 꺼진 출력을 낮은 파워로 켭니다. 이미 켜져 있으면 유지합니다.
    sg_ea.on().wait()
    sg_ec.on().wait()
    sg_ea.set_power(0.05, unit='Vpp').wait()
    sg_ec.set_power(0.05, unit='Vpp').wait()

    ea_ch1 = scope_ea.acquire('ch1_vpp').wait()
    ea_ch2 = scope_ea.acquire('ch2_vpp').wait()
    ec_ch1 = scope_ec.acquire('ch1_vpp').wait()
    ec_ch2 = scope_ec.acquire('ch2_vpp').wait()

    if ea_ch1 is None or ea_ch2 is None or not (ea_ch1 >= 0.2 and ea_ch2 <= 0.03):
        raise RuntimeError(f'check amp or connection — EA: CH1={ea_ch1} Vpp, CH2={ea_ch2} Vpp')
    if ec_ch1 is None or ec_ch2 is None or not (ec_ch1 >= 0.2 and ec_ch2 <= 0.03):
        raise RuntimeError(f'check amp or connection — EC: CH1={ec_ch1} Vpp, CH2={ec_ch2} Vpp')

    sg_ea.set_power(0.16, unit='Vpp').wait()
    sg_ec.set_power(0.19, unit='Vpp').wait()

    # Reference는 장비 공통 설정이므로 2g도 한 번만 적용합니다.
    wf_760.set_internal_reference('internal 10mhz').wait()
    wf_2g_ch1.set_external_reference(10e6).wait()
    wf_3g.set_external_reference(10e6).wait()
    # 외부 기준 입력을 설정합니다. 물리적 lock 대기/재시도는 하지 않습니다.
    anapico.set_external_reference(10e6).wait()
    anapico.set_frequency(7379e6).wait()
    anapico.on().wait()

    wf_760.set_frequency(5260e6).wait()
    wf_760.on().wait()
    wf_760.set_power(3).wait()

    wf_2g_ch1.set_frequency(2120e6).wait()
    wf_2g_ch1.on().wait()
    wf_2g_ch1.set_power(-6).wait()

    wf_2g_ch2.set_frequency(2120e6).wait()
    wf_2g_ch2.on().wait()
    wf_2g_ch2.set_power(-6).wait()

    wf_3g.set_frequency(3069.5e6).wait()
    wf_3g.on().wait()
    wf_3g.set_power(3).wait()

    dds_ch1.set_frequency(110e6).wait()
    dds_ch1.set_phase(0).wait()
    # DDS ON resets VVA to zero; apply the desired VVA after enabling output.
    dds_ch1.on().wait()
    dds_ch1.set_vva(400).wait()

    dds_ch3.set_frequency(200e6).wait()
    dds_ch3.set_phase(0).wait()
    dds_ch3.on().wait()
    dds_ch3.set_vva(400).wait()
