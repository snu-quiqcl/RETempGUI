HOM 실험 사용법
==============

기존 프로그램을 다시 실행한 뒤 장비 > FPGA > HOM 탭을 사용합니다.
FPGA를 연결하고 왼쪽에서 시퀀스 변수와 입출력 매핑을 설정합니다.
Run HOM은 단독 실행, Add to Queue는 현재 설정의 사본을 Queue에 추가합니다.
Queue 탭에서 순서, 반복 횟수, 실패 정책을 설정하고 Queue 실행을 누릅니다.
Queue에 추가한 후 HOM 탭 설정을 변경해도 이미 추가한 작업의 설정은 바뀌지 않습니다.
Queue 작업은 Queue의 steps 하위에 결과를 저장합니다.

AOMB
----
Control AOMB 체크박스, 물리적 Port/Pin, acquisition level, cleanup level을 설정합니다.
Port 0은 ja/jb, Port 2는 jc/jd 출력입니다. 선택한 포트에 해당하는 핀만 표시됩니다.
기본값은 jc_1 / Port 2, 시작 1 / 종료 1입니다. AOMA/C/TRIG와 중복 사용은 거절됩니다.
AOMA/C/TRIG는 타이밍을 유지하기 위해 빠른 Port 0을 사용합니다.
핀 이름은 FPGA 커넥터의 물리 핀 이름입니다. EOM이나 다른 실험 출력은 변경하지 않습니다.

타이밍 및 카운트
---------------
시간 입력 단위는 µs입니다. 0.01 µs = 시퀀서 1 clock, stopwatch bin은 별도로 1.25 ns입니다.
원본에서 실제로 사용하던 OFF 대기 25 clocks를 기본값으로 유지했습니다.
매 inner trial: AOMA/C OFF -> OFF 대기 -> TRIG -> stopwatch -> AOMA/C ON -> 카운트 계산.
그룹 시작에는 Group cooling이 적용됩니다. 계산 도중 ON으로 냉각하며 다음 trial에서 다시 OFF합니다.
유효 SYNC가 있는 trial만 분모에 넣습니다. PMTA/C의 서로 다른 lower bin을 각각 적용합니다.
M개의 PMTA, M개의 PMTC, 2M개의 HOM bin을 모두 수집합니다. 추가 Δt 창은 적용하지 않습니다.
HOM index M이 시간차 0이며 Δt=(index-M)*1.25 ns=PMTC-PMTA입니다.
M은 3의 배수이고 최대 255입니다. 메모리는 4M words를 사용합니다.
Trials/batch = Cooling groups × Trials/group × FPGA loops/batch.
전체 batch 수 = Batches/block × Blocks. 도중에 자동으로 batch를 분할하지 않습니다.
하나의 histogram bin이 65535를 초과하면 포화 플래그로 검출해 해당 batch를 제외하고 실패 처리합니다.
그 경우 Trials/group, Cooling groups 또는 FPGA loops/batch를 줄이고 PC batch 수를 늘릴 수 있습니다.

화면과 정규화
-------------
PMTA/PMTC/Total을 누적 및 최근 batch decay 그래프에 표시합니다. Y축은 log이며 0은 그리지 않습니다.
하단은 각 batch의 PMTA/PMTC/Total 적분 카운트입니다.
p_PMTA=A/N, p_PMTC=C/N, Total decay counts/trial=(A+C)/N.
Total은 평균 검출수이며 '한 개 이상 검출될 확률'과 다릅니다.
P(HOM)=전체 HOM coincidence/N. 확률 곡선은 각 HOM bin의 count/N입니다.
N은 valid SYNC trials입니다.
Distinguishable reference는 50:50 BS, 동일 기여도, 낮은 검출확률 근사에서
P(reference)=0.5*p_PMTA*p_PMTC입니다. 추가 reference 보정은 하지 않습니다.
각 시간차 bin의 reference는 PMTC와 PMTA decay histogram의 cross-correlation/(2*N^2)입니다.
누적 reference는 각 batch reference를 그 batch의 N으로 가중 평균합니다.
따라서 신호가 batch마다 변할 때 누적 reference는 누적 p_PMTA*p_PMTC/2와 다를 수 있습니다.
HOM/reference도 표시합니다. reference=0이면 비율은 표시하지 않습니다.
예상 trials/coincidence=1/P(HOM), 예상 seconds/coincidence=수집된 batch 경과시간/총 coincidence.
이는 batch 완료와 FIFO 수신까지의 경과시간에 기반한 평균 추정치이며 개별 사건 대기시간이 아닙니다.
기하분포, fitting, 실행 중 analysis 설정, coincidence별 attempt index는 없습니다.

저장 및 중단
-----------
기본 저장 위치: labremote/data/hom/YYYY-MM-DD/<run>.
configuration.json: 실제 실행 설정, 시간 단위, FPGA 이름, 소스 해시.
source/: 실행 시점의 HOM 코드, 시퀀서 컴파일러 및 하드웨어 정의 사본.
raw_fifo.csv: 비정상/미완성 batch를 포함한 수신 원본; structurally_valid는 형식 검증만 뜻합니다.
batches.jsonl: 프로토콜, trial 수, 포화 여부까지 검증된 완전한 batch.
histogram.json / histogram.csv / hom.png: 유효 batch의 누적 결과 및 그래프.
result.json: 성공/중단/실패, cleanup 상태와 metrics.
Stop은 부분 결과를 저장합니다. 완료하지 못한 batch는 raw에만 남고 확률 분모에 넣지 않습니다.
정상 완료, 중단, 오류 시 TRIG=0, AOMA/C=1, AOMB=설정된 cleanup level을 적용합니다.
장치 통신 오류나 cleanup 실패 때는 복구 완료로 간주하지 않습니다.
FPGA를 다른 측정과 동시에 사용하지 못하도록 기존 worker 독점 잠금을 사용합니다.

Workflow API
------------
def main(devices):
    return devices.fpga('fpga_local').run_hom(
        settings=devices.parameters['settings'],
        directory=devices.run_directory).wait()

또는 settings_file 인자로 저장한 HOM profile JSON을 읽을 수 있습니다.
UI의 Add to Queue는 labremote/workflow/queue_hom.py와 설정을 자동으로 묶습니다.

검증 범위
---------
tests/test_hom.py: vendor 명령 모의 실행, 타이밍 분기, SYNC/overflow,
확률 정규화, 가짜 FPGA 기반 단독/Queue 실행, 중단, timeout, cleanup 실패, Qt UI 설정.
실제 FPGA와 광학 신호에 대한 검증은 별도로 수행해야 합니다.
