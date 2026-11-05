HOM 실험 사용법
==============

기존 프로그램을 다시 실행한 뒤 장비 > FPGA > HOM 탭을 사용합니다.
FPGA를 연결하고 왼쪽에서 시퀀스 변수와 입출력 매핑을 설정합니다.
Run HOM은 단독 실행, Add to Queue는 현재 설정의 사본을 Queue에 추가합니다.
Queue 탭에서 순서, 반복 횟수, 실패 정책을 설정하고 Queue 실행을 누릅니다.
Queue에 추가한 후 HOM 탭 설정을 변경해도 이미 추가한 작업의 설정은 바뀌지 않습니다.
Queue 작업은 Queue의 steps 하위에 결과를 저장합니다.

출력 이름 및 FPGA 핀 정의
------------------------
HOM 출력은 AOMA, AOMC, TRIG, AOMB, AOMM 등의 논리 이름으로 선택합니다.
목록과 물리 핀 연결은 labremote/devices/fpga/vendor/HardwareDefinition_remote_ent_test_ec.py의
input_mapping / output_mapping에서 가져옵니다. 포트 및 bit의 기본 정의는 같은 폴더의
HardwareDefinition_v4_04.py를 사용합니다. 정의를 변경한 뒤 프로그램을 다시 시작합니다.
HOM 설정에는 출력 이름만 저장하며 실제 실행에서 해석된 pin/port/bit도 configuration.json에 보관합니다.
Control AOMB 및 acquisition level / cleanup level은 그대로 설정할 수 있습니다.
AOMA/C/TRIG는 타이밍 유지를 위해 빠른 포트에 정의된 출력만 선택할 수 있습니다.
중복된 물리 출력을 동시에 할당할 수 없습니다.

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
전체 batch 수는 Batches 하나로 지정합니다. 기존 profile/Queue는 Batches/block × Blocks로 자동 이전합니다.
Inner trials/group은 inner loop이며, Group-loop repeats/batch는 냉각 그룹 반복을 묶는 바깥 FPGA loop입니다.
도중에 자동으로 batch를 분할하지 않습니다.
하나의 histogram bin이 65535를 초과하면 포화 플래그로 검출해 해당 batch를 제외하고 실패 처리합니다.
그 경우 Trials/group, Cooling groups 또는 FPGA loops/batch를 줄이고 PC batch 수를 늘릴 수 있습니다.

화면과 정규화
-------------
PMTA/PMTC/Total을 누적 및 최근 batch decay 그래프에 표시합니다. Y축은 log이며 0은 그리지 않습니다.
하단 왼쪽 축은 각 batch의 PMTA/PMTC/Total 적분 카운트, 오른쪽 축의 점선은 각 카운트/해당 batch SYNC trials (%)입니다.
누적 및 최근 batch decay에 PMTA/PMTC/Total 각각 A*exp(-(t-t0)/tau)+background fitting을 표시합니다.
각 채널 lower bin 이후의 피크부터 마지막 bin까지 사용합니다. Total은 두 lower bin 중 큰 값 이후부터 사용합니다.
fit는 기존 Decay의 count 기반 가중 fitting을 재사용하며 데이터 부족/실패 시 unavailable을 표시합니다.
이 표시는 HOM 확률이나 reference 정규화를 변경하지 않습니다.
p_PMTA=A/N, p_PMTC=C/N, Total decay counts/trial=(A+C)/N.
Total은 평균 검출수이며 '한 개 이상 검출될 확률'과 다릅니다.
P(HOM)=전체 HOM coincidence/N. 확률 곡선은 각 HOM bin의 count/N입니다.
N은 valid SYNC trials입니다.
Distinguishable reference는 50:50 BS, 동일 기여도, 낮은 검출확률 근사에서
P(reference)=0.5*p_PMTA*p_PMTC입니다. 추가 reference 보정은 하지 않습니다.
각 시간차 bin의 reference는 PMTC와 PMTA decay histogram의 cross-correlation/(2*N^2)입니다.
누적 reference는 각 batch reference를 그 batch의 N으로 가중 평균합니다.
따라서 신호가 batch마다 변할 때 누적 reference는 누적 p_PMTA*p_PMTC/2와 다를 수 있습니다.
Total visibility = 1 - P(HOM)/P(reference), 전체 수신 시간차 bin을 적분한 값입니다.
퍼센트로 표시하고 reference=0이면 표시하지 않습니다. 음의 값도 임의로 0으로 자르지 않습니다.
Estimated trials/coincidence 및 estimated seconds/coincidence는 표시/계산에서 제거했습니다.
SYNC-confirmed trials는 PMT 검출이 없어도 SYNC가 확인된 시도 수입니다.
Trials without SYNC는 SYNC stopwatch 완료 플래그가 없었던 시도 수이며, photon count와 다릅니다.
기하분포, 실행 중 analysis 설정, coincidence별 attempt index는 없습니다.

저장 및 중단
-----------
기본 저장 위치: labremote/data/hom/YYYY-MM-DD/<run>.
results.json: 하나로 통합한 데이터 파일입니다.
  configuration: 실제 설정, 해석된 출력 핀, 시간 단위, FPGA 이름, 소스 해시.
  final: 완료된 모든 배치의 누적 histogram, counts, trials, probabilities, fitting.
  axes: decay 시간축과 HOM 시간차축(ns).
  batches: 배치별 전체 histogram과 통신 시각/소요 시간, 완료·실패·중단 상태.
  final.decay_fit: 누적/최근 batch의 PMTA, PMTC, Total fit 결과와 시작 bin.
  최상위: 실행 시작/종료, 전체 경과시간, 실행 상태, cleanup 상태 및 metrics.
raw_fifo.csv: 비정상/미완성 batch를 포함한 수신 원본과 PC 수신 시각.
  run_id, batch, row_index로 식별합니다. structurally_valid는 형식 검증만 뜻합니다.
hom.png: 완료한 batch들의 누적 결과 및 fitting 그래프. 중단/실패 시에도 저장합니다.
source/: 실행 시점의 HOM 코드, 시퀀서 컴파일러 및 하드웨어 정의 사본.
새 실행은 configuration.json/histogram.json/histogram.csv/result.json/decay_fit.json/batches.jsonl을 따로 만들지 않습니다.
Open result에서 results.json을 열 수 있고, 기존 분리 저장 형식의 result.json도 계속 읽습니다.

통신 시각은 timezone이 포함된 PC 시각이며 배치별 started_at, upload_started_at,
upload_finished_at, sequencer_started_at, first_fifo_received_at, last_fifo_received_at,
finished_at을 기록합니다. 단계에 도달하지 못한 시각은 null입니다.
timings_s에는 upload, start_commands, status_poll, fifo_read, stale_flush 및 그 합계
communication_calls가 초 단위로 기록됩니다. 고해상도 단조 시계로 측정합니다.
API 호출 시간에는 PC 소프트웨어/드라이버 처리 및 대기가 포함되고 upload에는 인코딩도 포함됩니다.
따라서 순수 전선 전송 시간이나 FPGA 내부 광자 검출 시각을 의미하지 않습니다.
results.json은 배치 시작/종료 및 실험 종료 시 임시 파일 교체 방식으로 갱신됩니다.
강제 종료 후 남은 running 상태 파일은 Open result에서 interrupted로 표시됩니다.
Stop은 부분 결과를 저장합니다. 완료하지 못한 batch의 수신 원본은 raw에,
실패/중단 상태와 시간은 results.json의 batches에 남고 확률 분모에는 포함하지 않습니다.
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
