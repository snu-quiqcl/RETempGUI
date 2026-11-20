# AFG2105 제어 탭

Linux instrumentserver에 `lab_afg2105.AFG2105` 드라이버를 설치하고
`afg2105` 등의 이름으로 등록합니다. UI PC에는 이 드라이버나 USB 연결이 필요하지 않습니다.

1. UI의 서버 Host/Port를 Linux instrumentserver로 설정합니다.
2. `Rescan server devices`를 실행합니다. AFG2105는 RF 장비로 자동 인식됩니다.
3. `RF → AFG2105 → 장비 이름`에서 Connect를 누릅니다.
   검색으로 추가되지 않으면 Add device에서 `afg2105` family와 실제 서버 장비 이름을 입력합니다.
4. Frequency(MHz/kHz/Hz), Amplitude(dBm), DC offset(V)을 입력한 뒤 각 Apply를 누릅니다.
5. RF ON / RF OFF로 출력을 제어합니다. Read는 해당 항목, Refresh는 전체 상태를 서버에서 조회합니다.

왼쪽 표시값은 서버에서 조회한 설정이며 입력칸은 다음 적용값입니다.
연결·조회·연결 해제는 장비 설정과 출력을 변경하지 않습니다. 끄려면 RF OFF를 누르세요.
장비 기본 단위가 Vpp여도 이 드라이버의 amplitude 파라미터는 dBm으로 반환합니다.

서버 드라이버의 sine/50 Ω 조건, 진폭 상한(이전에 제공한 config 기본 0 dBm),
진폭+offset 범위 검사가 그대로 적용됩니다. 서버가 거절한 설정은 오류로 표시됩니다.
UI 입력 범위는 하드웨어 범위이며 더 낮은 서버 상한을 자동 조회하지는 않습니다.
서버의 `initialize_sine: true` 설정을 사용하면 시작 시 필요한 모드가 준비되고 출력은 OFF입니다.

이 단계는 수동 장비 제어 탭입니다. Secular frequency scan과 PMT/SYNC 측정은 포함하지 않습니다.
