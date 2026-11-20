# Micromotion / Secular Frequency Scan

기존 Micromotion 탭의 네 번째 페이지입니다. 이 기능은 DAC를 연결하거나 초기화하지 않으며,
DAC 전압 읽기/쓰기/복원도 하지 않습니다. 냉각 AOM/레이저 출력 및 FPGA manual/auto 상태도 변경하지 않습니다.
실행 전에 냉각과 형광 검출을 기존 실험 조건으로 준비하세요.

## 사용

1. RF의 AFG2105 탭에서 Linux instrumentserver의 AFG2105를 연결합니다.
2. 사용할 FPGA를 연결하고 Micromotion → Secular Frequency Scan을 엽니다.
3. Connected AFG2105에서 소스를 선택합니다.
4. Modulation SYNC와 PMT 물리 입력을 지정합니다. 서로 달라야 하며 PMT 입력은
   count와 stopwatch를 모두 지원해야 합니다. 기본 EC=jb_4, EA=jb_6은 예제입니다.
5. Start/Stop/Step(kHz), AFG amplitude(dBm), AFG offset(V), settling을 설정합니다.
6. 목표 이벤트 수, phase bins, 최대 시도 수, 지점 timeout 및 count-rate 조건을 설정하고 Start를 누릅니다.

AFG source amplitude/offset은 DAC 보상 전압과 무관합니다. 실제 소스 상한은 서버 드라이버가 검사합니다.
스캔 시작 시 드라이버의 `configure_sine`으로 continuous sine/50 Ω/dBm을 설정하고
내부 AM/FM/FSK/Sweep을 비활성화한 뒤 출력을 켭니다. 이후 호스트가 주파수를 하나씩 변경합니다.
테스트한 외부 RF 변조 셋업에 연결하여 사용하며 SYNC는 이 변조 주파수의 기준 신호입니다.

## 측정과 피팅

각 주파수에서 평균 PMT count rate와 SEM을 측정한 다음, SYNC와 PMT stopwatch를 함께 시작하여
첫 PMT가 첫 SYNC보다 늦고 차이가 한 주기 이내인 이벤트만 누적합니다. SYNC 이후 모든 광자를
수집하는 time tagger가 아닙니다. 시간차 0은 제외합니다.

1.25 ns timestamp들을 지정한 phase bins로 합칩니다. 주파수 범위는 50..5000 kHz이고,
bin 개수는 해당 주기의 유효 timestamp 개수보다 클 수 없습니다. 기본값은 64 bins입니다.
원본 `Task/parameteric_heating/secular_frequency_scan.py`의 기하와 first-photon corrected
조건부 multinomial 피팅을 이식했습니다. 측정한 평균 count rate 오차도 반영합니다.

표시값은 형광 modulation, phase, 평균 count rate 및 선택한 주파수의 히스토그램/피팅입니다.
위상 정의는 `r(t)=R[1+M*cos(2*pi*f*t-theta)]`, `theta=atan2(b,a)`입니다.
기존 RF correlation 페이지의 phase 부호 규약과 혼동하지 마세요. 약한 응답의 phase는 unresolved입니다.
주파수 그래프를 클릭하면 해당 지점 히스토그램을 확인할 수 있습니다.
공진 중심/선폭의 자동 피팅이나 모드 자동 선택, DAC 자동 보상은 아직 포함하지 않습니다.

Count-rate background M은 원본의 첫 광자 선택 편향 지표로, 잔류 EMM 판정 기준이 아닙니다.
기본 상한 0.05를 넘으면 Stop, 또는 사용자가 선택하면 경고 후 계속합니다. 보정 모델을 쓰더라도
원본의 rate guard를 유지합니다. PMT count가 0이거나 피팅이 무효이면 부분 데이터를 저장하고 중단합니다.

## 종료와 저장

실행 중 같은 UI의 FPGA와 AFG를 점유합니다. 다른 탭의 source 설정/연결 해제는 차단됩니다.
별도 서버 클라이언트의 변경까지 잠그는 서버 lease는 없습니다.
Stop/완료/오류 시 AFG output OFF를 요청하고 조회 확인합니다. 통신 단절로 OFF 확인에 실패하면
cleanup failed를 기록합니다. AFG 주파수/진폭/offset은 마지막 스캔 설정으로 남습니다.
프로세스 강제 종료나 케이블 분리는 출력 OFF를 보장하지 못합니다.

results.json, raw_fifo.jsonl, 지점별 point_*.json, 실패/중단 시 partial_point.json,
frequency_scan.csv, secular_scan.png 및 FPGA 매핑 snapshot을 저장합니다.
최대 시도/timeout은 무한 대기를 막고, 진행 중인 FPGA block은 STOP/정리 후 반환합니다.
중단된 block의 raw FIFO는 보존하지만 완전한 측정 histogram에 더하지 않습니다.
EA/EC 및 FPGA별 설정 저장은 기존 설정 경로를 따르며 기존 Micromotion 페이지와 독립적입니다.

## 검증 범위

합성 first-event 분포, FPGA 명령 에뮬레이션, FIFO 검증, 장비 점유/중단/출력 OFF,
부분 저장 및 Qt 화면을 오프라인 테스트합니다. 실제 Linux 서버와 FPGA/이온에서의 실측은 별도입니다.
Count exposure는 원본 프로토콜의 WAIT n+3 규칙 및 n+4 gate 경계를 사용하며,
100 µs 이하 segment의 누적 live time입니다. segment 사이에는 dead gap이 있습니다.
정밀 count-rate 검증 시 실제 FPGA bitstream의 gate 시간을 확인해야 합니다.
