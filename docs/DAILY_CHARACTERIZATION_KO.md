# Daily characterization — Fluorescence / microwave Rabi

FPGA 창에서 `fpga_local` 옆의 `Daily characterization`을 엽니다. FPGA는 기존 창에서 한 번만 연결합니다. 새 COM 연결을 만들지 않습니다. Fluorescence는 PMT만 읽고, Rabi는 선택 FPGA 출력만 제어하며 microwave 발생기 설정은 외부에서 관리합니다.

## 화면

- **EA Fluorescence / EC Fluorescence**: 각각 변수 불러오기·저장, 개별 실행·중단, 이전 결과 열기, 시간 trace / histogram·Poisson / FFT 세 그래프를 제공합니다.
- **각 Fluorescence 탭의 PMT/AOM 선택**: 시퀀스의 PMT와 AOM을 현재 HardwareDefinition의 이름에 연결합니다. 기본값은 EA=`PMTFA`/`AOMA`, EC=`PMTFC`/`AOMC`입니다. PMT는 PMTA/PMTC/PMTFA/PMTFC 중 선택할 수 있습니다. AOMB/AOMM은 사용하지 않습니다.
- **Workflow**: 메인의 Workflow와 같은 위젯·실행 엔진입니다. 기본 예제는 EA 측정 완료 후 EC를 실행합니다. 실행 중지와 프로그램 종료도 기존 취소/종료 경로를 사용합니다.

각 탭에서 바꾼 변수와 PMT/AOM 매핑은 해당 탭의 실행에 바로 사용합니다. **변수 저장**을 누르면 같은 실험 JSON에 `roles`로 함께 저장되며, 이후 workflow도 이 저장값을 읽습니다. EA/EC Fluorescence와 Rabi는 각각 독립적입니다. 공유 역할 매핑 탭은 제거했습니다. 실행 시작 시 값을 복사해 고정하며 공유 HardwareDefinition 전역은 변경하지 않습니다. Fluorescence의 AOM 선택은 별칭 저장용으로, 출력을 바꾸지 않습니다.

## 설정 파일

`labremote/config/operations/characterization/`에 공개 기본값을 둡니다.

- `fluorescence_EA.json`, `fluorescence_EC.json`
- `rabi_EA.json`, `rabi_EC.json`
- `fpga_roles.json`: 이전 Fluorescence 설정을 읽기 위한 호환 기본값

GUI의 저장은 각 실험의 `fluorescence_EA.local.json`, `fluorescence_EC.local.json`, `rabi_EA.local.json`, `rabi_EC.local.json`을 생성합니다. 각 파일에 조건과 `roles` 매핑이 함께 들어갑니다. 이전 Fluorescence 파일에 roles가 없으면 기존 `fpga_roles.local.json`을 읽어 초기화하고, 탭에서 저장하면 독립 설정으로 전환됩니다. 이전 파일과 기존 mapping_file API는 호환성을 위해 유지합니다. 로컬 파일이 있으면 기본값보다 우선하며 Git에서 제외됩니다. 다른 PC에서는 이 로컬 파일들을 별도로 복사하세요.

```json
{
  "schema_version": 1,
  "chamber": "EA",
  "exposure_ms": 0.5,
  "num_average": 500,
  "num_repeat": 20,
  "timeout_s": 60,
  "roles": {"PMT": "PMTFA", "AOM": "AOMA"}
}
```

원본의 NUM_AVERAGE는 한 FPGA 실행에서 수집하는 **샘플 수**입니다. 평균 하나로 합치지 않습니다. NUM_REPEAT는 그 실행을 반복하는 횟수입니다. 기본 총 샘플은 10,000개입니다. Exposure는 원본 100 µs 반복 구조에 맞춰 0.1 ms 단위로 제한하며 잘못된 값을 조용히 반올림하지 않습니다. Timeout은 배치별 제한이며 배치의 명목 수집 시간보다 커야 합니다. 전체 샘플은 3~1,000,000개로 제한합니다.

```json
{
  "schema_version": 1,
  "setup": "EC",
  "routes": {
    "EA": {"PMT": "PMTFA", "AOM": "AOMA"},
    "EC": {"PMT": "PMTFC", "AOM": "AOMC"}
  }
}
```

setup은 물리적인 EC FPGA 셋업이고 chamber는 실험 대상입니다. 오븐의 chamber 설정과 독립적입니다. 현재 FPGA가 사용하는 `HardwareDefinition_remote_ent_test_ec`를 그대로 사용합니다.

## Workflow API

```python
def main(devices):
    fpga = devices.fpga("fpga_local")
    ea = fpga.run_fluorescence("EA").wait()
    ec = fpga.run_fluorescence("EC").wait()
    print(ea["summary"], ec["summary"])
```

파일을 명시할 수도 있습니다. 경로는 UI PC의 경로입니다.

```python
result = fpga.run_fluorescence(
    "EA",
    settings_file="D:/lab/fluorescence_EA.local.json",
    directory="D:/lab/data/daily",
).wait()
```

`settings={...}`를 전달하면 파일 대신 해당 값을 사용합니다. settings와 settings_file은 함께 지정할 수 없습니다. `stop_fluorescence()` 또는 실행 handle의 `request_cancel()`로 중단합니다. 메인 Workflow에서 실행해도 같은 FPGA worker에 연결된 EA/EC 탭으로 진행 및 최종 결과가 전달됩니다. 화면 대상은 chamber로 고정하고 run_id로 실행을 구분합니다. 두 탭이 하나의 FPGA를 공유하므로 동시 실행을 거부하고, 기존 count/repeat/scan과의 충돌도 막습니다.

## 데이터와 분석

각 실행은 고유 디렉토리를 생성합니다.

- `configuration.json`: 실행 변수·매핑·HardwareDefinition 이름·실행 ID·코드 해시
- `raw_fifo.csv`: 배치 번호, 원본 FIFO 행, 유효성. 수신 청크마다 기록합니다.
- `result.json`: 완료/실패/중단, 샘플 수, 결과 요약, 오류
- `analysis.npz`, `time_trace.csv`, `histogram.csv`, `fft.csv`, `analysis.png`

그래프와 분석은 수집 완료 또는 중단 후 생성합니다. 수집 중에는 샘플 수와 배치 진행률을 표시합니다. 분석은 GUI thread 밖에서 수행하며 탭에서는 결과를 그립니다. 데이터가 없으면 분석 파일 대신 실패/중단 상태와 원본 기록만 남습니다. 손실된 샘플을 0 photon으로 채우지 않습니다. 취소 시 sequencer 정지와 선택 PMT counter 비활성화를 시도하며, 정리 실패는 오류로 남습니다. 오류나 취소는 workflow의 wait()에서 예외로 전달되고 다음 실험으로 자동 진행하지 않습니다.

원본 계산을 유지합니다: 시간축은 exposure×샘플 번호, Poisson λ는 평균 count, FFT는 평균 제거→Hann window→rFFT→원본과 동일한 one-sided PSD 정규화입니다. **원본과 같이 배치 사이 재시작/PC 대기 시간은 시간축과 FFT에서 제외됩니다.** 따라서 실제 무중단 샘플링의 주파수 분석과 동일하다고 해석하면 안 됩니다. 이 가정은 설정/결과에도 기록됩니다. 상수 신호는 의미 있는 FFT peak가 없으므로 null로 표시하고, 3개 미만 부분 샘플에는 FFT를 만들지 않습니다.

## 고정 microwave Rabi operation

Rabi는 외부에서 설정된 microwave 상태를 유지하면서 FPGA 펄스 시간만 스캔하는 operation입니다. **주파수 설정, RF 출력 ON/OFF, 주파수 정착 대기는 operation 외부에서 관리합니다.** Rabi 내부에는 주파수 loop나 AnaPico API 호출이 없습니다. Ramsey/SPAM도 같은 FPGA 전용 operation 구조를 사용합니다.

### 장비 설정과 화면

`apsyn420_mw`는 기존 RF → AnaPico GUI/API에서 설정합니다. 기존 개인 Configuration을 사용한다면 필요할 때 아래 항목을 추가하고 RF 그룹을 연결하세요. Rabi operation 자체는 AnaPico 연결을 요구하지 않습니다.

```json
{"family":"anapico","name":"apsyn420_mw","group":"RF","enabled":true}
```

EA Rabi / EC Rabi 탭은 측정 조건과 FPGA 역할 매핑, Run/Stop, 결과 저장 폴더와 이전 결과 열기를 제공합니다. 주파수 start/end/step, microwave instrument, frequency settle 입력은 제거했습니다.

- EA 기본 매핑: PMTFA, AOMA, MW_A, EOM_7GA1, EOM_7GA2, EOM_2GA
- EC 기본 매핑: PMTFC, AOMC, MW_C, EOM_7GC1, EOM_7GC2, EOM_2GC

냉각 시간·반복, AOM wait, 초기화·검출 시간, microwave pulse step, pulse points, shots, threshold, 점당 timeout은 각 탭에서 설정합니다. 기본값은 10 us 간격, 0부터 10개 시간점, 점당 500 shots, threshold 2입니다. GUI 시간은 us이며 JSON의 T_* / WAIT_AOM은 원본과 같은 10 ns clock 정수입니다. shots 최대 1024, 전체 shots 최대 2,000,000 제한을 유지합니다.

### 실행 범위와 종료

GUI/API는 기존 비동기 실행·취소·로그 기반을 재사용하지만, 실제 FPGA 작업은 한 개의 `RABI_ACQUIRE` operation입니다. 이 operation 안에서 준비 → 모든 pulse 시간점 측정 → FPGA 정리를 수행합니다. 각 시간점마다 별도 workflow operation을 제출하지 않습니다. FPGA 시퀀스의 냉각·초기화·MW gate pulse·PMT 검출 순서는 유지합니다.

operation이 실행되는 동안 외부 제어자는 microwave 주파수와 출력을 고정해야 합니다. **완료·중단·timeout 때도 AnaPico 출력은 바꾸지 않습니다.** FPGA는 MW gate LOW, PMT counter OFF, EOM_2G LOW, 선택 AOM/EOM_7G_1/2 HIGH(cooling)로 정리합니다. 이는 기존 상태 복원이 아닙니다. FPGA 정리 실패는 오류로 남습니다. 다른 FPGA 작업과 동시 실행은 거부하지만 microwave는 외부 제어 범위이므로 예약하지 않습니다.

### 설정 파일 이전

`rabi_EA.json`, `rabi_EC.json`과 저장되는 `rabi_EA.local.json`, `rabi_EC.local.json`은 schema_version 2입니다. 조건과 `roles`를 함께 저장하며 microwave 장비명·주파수 scan·정착 설정은 포함하지 않습니다.

이전 schema 1 파일은 frequency start=end인 경우 나머지 조건/매핑을 유지하여 읽습니다. 이전 microwave 관련 필드는 제거되며 저장 시 schema 2가 됩니다. 이전 주파수 값은 실제 장비의 현재 값이라고 간주하지 않고 결과에도 자동 기록하지 않습니다. start≠end인 파일은 조용히 단일 주파수로 바꾸지 않고 외부 workflow로 옮기라는 오류를 표시합니다. 원본 파일은 GUI에서 저장하기 전까지 수정하지 않습니다.

### Operation API

```python
# Microwave frequency/output must already be set externally.
result = devices.fpga("fpga_local").run_rabi("EA").wait()
```

`settings=...`, `settings_file=...`, `directory=...`를 사용할 수 있습니다. microwave API 인자를 받던 이전 호출은 제거했으므로 `run_rabi("EA", mw)`는 새 형식으로 수정해야 합니다. 기존 Single Scan / Fluorescence API는 유지합니다.

외부 주파수 workflow는 주파수 설정 및 정착을 마친 뒤 매 주파수에서 위 operation을 호출하면 됩니다. 그때 결과에 주파수를 기록하려면 `frequency_hz=...`를 전달할 수 있습니다. **이 값은 호출자가 제공하는 메타데이터이며 하드웨어 설정 또는 읽기 요청이 아닙니다.** 생략하면 null이며 UI는 External microwave로 표시합니다. 외부 workflow가 microwave 종료와 취소 시 정리까지 책임져야 합니다.

`stop_rabi()` 또는 handle.request_cancel()로 operation을 중단합니다. GUI 실행과 외부 workflow 호출 모두 같은 EA/EC 탭에 결과를 전달합니다. `labremote/workflow/daily_rabi.py`는 외부 설정을 마친 뒤 EA operation 한 번을 호출하는 예시입니다. 주파수 스캔 workflow는 이 operation과 별도로 작성합니다.

### 결과

각 시간점의 bright population을 실시간으로 표시하고, 완료/중단 후 photon histogram과 pulse time vs population/fit을 표시합니다. Rabi frequency와 π time은 위쪽 요약에 표시합니다. 단일 operation에는 microwave 주파수 스캔 그래프가 없습니다. 이전 다중 주파수 결과 파일은 기존 그래프로 열 수 있습니다.

원본 `counts >= threshold` 비율 및 `A*sin(pi*f*t)^2+C` 모델을 유지합니다. 원본의 count clipping은 제거하여 수신 counts를 그대로 보존합니다. 피팅 실패는 초기 추정값으로 대체하지 않습니다. 시간축은 원본 pulse step 기준 명목 시간이고 wait/branch 보정(-7 clocks)을 유지합니다.

실행별 `configuration.json`, `raw_fifo.csv`, `points.json`, `population.csv`, `analysis.json`, `analysis.png`, `result.json`을 저장합니다. 주파수 CSV 열은 `frequency_hz_metadata`로 표시합니다. 미완료 시간점의 수신 값은 raw_fifo.csv에 남고, 완전한 시간점만 분석합니다. 외부 microwave 제어 여부와 주파수 메타데이터의 미지정 상태도 기록합니다.

## EA/EC Ramsey와 SPAM

Daily characterization에 EA Ramsey, EC Ramsey, EA SPAM, EC SPAM 탭을 추가했습니다. 각 탭에서 측정 조건과 PMT/AOM/MW/EOM 역할을 함께 저장·불러오고, 개별 Run/Stop 및 이전 결과 열기를 사용할 수 있습니다. 저장 파일은 `labremote/config/operations/characterization/ramsey_EA.local.json`, `ramsey_EC.local.json`, `spam_EA.local.json`, `spam_EC.local.json`입니다. 공개 기본값은 같은 이름의 `.json` 파일입니다. 이 네 로컬 파일도 다른 PC에 별도로 복사하세요.

역할 기본값은 Rabi와 동일하게 EA=PMTFA/AOMA/MW_A/EA EOM, EC=PMTFC/AOMC/MW_C/EC EOM입니다. 각 실험 파일은 서로 독립적이며, 한 탭의 매핑 변경이 다른 실험에 적용되지 않습니다.

두 실험 모두 **microwave 발생기의 주파수·출력 ON/OFF를 읽거나 변경하지 않습니다.** FPGA의 gate와 counter만 제어합니다. 준비·전체 측정·정리가 각각 단일 `RAMSEY_ACQUIRE`, `SPAM_ACQUIRE` operation 안에서 실행됩니다. 종료와 중단 때 선택 MW gate LOW, counter OFF, EOM_2G LOW, AOM/EOM_7G_1/2 HIGH(cooling)로 정리합니다. 발생기 출력은 외부에서 관리해야 하며, 통신 오류로 정리가 확인되지 않으면 오류를 기록합니다.

### Ramsey

제공된 `sequencer_ramsey.py`의 냉각 → 초기화 → half π pulse → free precession → half π pulse → 검출 순서와 FPGA 내부의 precession/shot 반복을 유지합니다. FPGA 프로그램을 한 번 올리고 전체 delay scan의 FIFO를 읽습니다.

GUI에서 냉각/검출 반복, 초기화·검출·AOM off wait, half π pulse, precession step, delay points, shots, threshold, 전체 scan timeout, 피팅 주파수 범위를 설정합니다. 피팅 범위 min=max=0이면 sampled Nyquist band 전체를 사용합니다. 시간은 GUI에서 us, JSON에서는 10 ns clock 정수입니다.

원본 실행값을 기본값으로 사용합니다: cooling 400 us×10, init 10 us, detection 50 us×1, half π 29.48 us(원본 `int(29.485e2)`의 절삭 결과), precession step 500 us, 20 points, 점당 100 shots. 원본에는 실행 중인 half π 값이 하나만 있어 EA/EC 모두 같은 초기값을 사용합니다. 각 탭에서 대상 이온에 맞는 보정값을 저장하세요. 원본의 사용되지 않는 T_init_repeat/T_wait_for_aom_on은 새 기능으로 활성화하지 않았습니다.

분석은 원본의 binomial-deviance 다중 초기값 피팅과 exponential envelope를 유지합니다. 실제 bright/received 비율, 안정화된 binomial 오차, Ramsey frequency, T2*, 불확실성과 BIC 판정을 저장합니다. 주파수 또는 decay가 분해되지 않으면 확정된 측정값으로 표시하지 않습니다. hist 마지막 40-bin은 overflow를 포함하며 raw counts는 보존합니다. 시간축은 원본과 같은 명목상 precession step 기준입니다.

수신이 중단된 시간점도 실제 받은 shots 수로 분석하며, 미수신 데이터를 0으로 채우지 않습니다. 완전한 시간점 개수와 부분 결과 상태를 구분합니다. 유효 시간점이 6개 미만이면 피팅 불가를 표시합니다.

### SPAM

제공된 `sequencer_spam.py`의 두 조건, 즉 **MW pulse 없음(target 0)** 및 **π pulse(target 1)**을 각 N_repeat에서 순서대로 반복합니다. 여기서 MW off는 FPGA gate에 pulse를 주지 않는다는 뜻이며 발생기 출력 OFF가 아닙니다.

기본값은 cooling 500 us×2, init 1.5 us, detection 80 us, AOM wait 0.5 us, batch당 500 attempts, 상태별 10회 반복입니다. π pulse는 원본의 EA=76.77 us, EC=59.96 us를 사용합니다. 조건별 attempts는 기본 5,000회입니다.

원본의 사전선별 코드가 주석 처리되어 있으므로 이를 새로 활성화하지 않았습니다. 현재 시퀀스에서는 보통 N_success=N_average입니다. FIFO의 `[N_success, address, count, 10]`를 검증하고 각 batch마다 address<N_success인 행만 final detection에 포함합니다. 0 photon은 유효 데이터로 유지하고 batch 경계를 보존합니다.

두 상태의 누적 population histogram(로그 Y축), target 0이 bright로/target 1이 dark로 판별된 비율, 두 상태 동일 가중 평균 SPAM error와 fidelity를 표시합니다. accepted 데이터가 0개인 상태의 conditional error/fidelity는 0이나 100%로 대신하지 않고 N/A로 표시합니다. 부분 readout은 received와 accepted 수 및 incomplete batch로 구분합니다. histogram의 마지막 39-bin은 overflow이고 raw counts는 자르지 않습니다.

### 호출 및 결과 저장

```python
# Microwave settings/output are managed externally before these calls.
fpga = devices.fpga("fpga_local")
ramsey = fpga.run_ramsey("EA").wait()
spam = fpga.run_spam("EC").wait()
```

`settings`, `settings_file`, `directory`, 선택적인 `frequency_hz` 메타데이터 인자를 사용할 수 있습니다. frequency_hz는 주파수 설정 명령이 아닙니다. `stop_ramsey()`, `stop_spam()` 또는 handle.request_cancel()로 중단합니다. 다른 FPGA 측정과 동시에 실행하지 않습니다.

실행별 `configuration.json`(조건·역할·원본 적응 코드 해시), `raw_fifo.csv`, `points.json`, `summary.csv`, `analysis.json`, `analysis.png`, `result.json`을 저장합니다. 분석 JSON의 비유한 불확실성 값은 null로 저장하고 status/분해 여부를 함께 남깁니다. GUI와 외부 workflow API의 결과는 같은 해당 EA/EC 탭으로 전달됩니다.

## EA/EC Initialization

Daily Characterization에 EA Initialization과 EC Initialization 탭을 추가했습니다. 변수와 PMT/AOM/EOM/MW gate 역할 매핑은 각 탭에서 독립적으로 저장·불러오기 할 수 있습니다. MW gate 매핑은 공통 FPGA 종료 정리에 사용하며, initialization 시퀀스는 MW 펄스를 발생시키지 않습니다.

원본 `init_measurement_refactored.py`처럼 초기화 인덱스 0부터 `N_init_control-1`까지 한 sequencer 프로그램에서 순회합니다. 기본값은 cooling 500 us × 6, initialization step 0.2 us, 21개 시간점, 지점당 500회, detection 80 us, threshold >= 4입니다. 표시 시간은 원본과 같은 명목상 index × step입니다.

원본의 `T_det_repeat`는 선언되어 있지만 실제 반복 명령이 없어서 1로 고정합니다. 이 값을 늘리는 새로운 동작은 추가하지 않았습니다. PMT raw count는 histogram의 표시 상한으로 잘라 저장하지 않습니다.

각 탭에 마지막 시간점 histogram, 시간별 bright population/오차, `A exp(-t/tau)+offset` 피팅 결과 tau를 표시합니다. 원본처럼 t=0은 fitting에서 제외하며, 추가로 미완료 시간점도 fitting에서는 제외합니다. 데이터 부족·contrast 없음·피팅 실패는 미해결로 표시합니다. 중단 시 실제로 수신한 횟수만 분모로 사용하고 부분 데이터를 저장합니다.

```python
result = devices.fpga('fpga_local').run_initialization(
    'EA', settings_file='labremote/config/operations/characterization/initialization_EA.local.json',
    directory='D:/ExperimentData'
).wait()
```

`settings_file`을 생략하면 해당 chamber의 local 설정, 없으면 기본 JSON을 사용합니다. `settings`로 설정 객체를 직접 전달할 수도 있습니다. 중단은 `stop_initialization()` 또는 실행 handle의 `request_cancel()`입니다. 하나의 `INITIALIZATION_ACQUIRE` operation으로 FPGA만 제어하며, 모든 종료 경로에서 기존 FPGA cleanup을 수행합니다.

주파수별 Rabi와 파일 보관 방법은 [실험 조건 라이브러리와 저장 가이드](EXPERIMENT_ARCHIVE_KO.md)를 참고하세요.

## 수집 중 그래프

Ramsey와 Initialization은 한 시간점의 shots가 모두 수신될 때마다 population 점과 해당 시간점 histogram을 갱신합니다. SPAM은 각 상태의 batch가 완료될 때마다 누적 histogram(로그 Y축), 상태별 오류율과 동일 가중 평균을 갱신합니다. 아직 데이터가 없는 상태의 오류율은 N/A입니다. 완료되지 않은 포인트/batch는 중간 그래프에 합산하지 않으며 기존 부분 저장과 종료 분석 정책은 유지합니다.

중간 표시는 작은 집계 결과만 UI에 전달하고, 축과 그래프 객체를 유지한 채 데이터를 갱신합니다. FPGA가 FIFO 데이터를 전달하기 전에는 표시할 수 없으며, 여러 지점이 한 번에 수신되면 화면 갱신도 합쳐질 수 있습니다. Ramsey/Initialization fitting은 수집 종료(중단 포함) 후에만 수행합니다. 측정 명령, 원시 데이터와 파일 형식은 변경하지 않았습니다.

## 장비 메뉴

장비 메뉴에서 RF/FPGA 등 그룹 이름을 바로 누르면 해당 상세 창이 열립니다. 메뉴 안의 추가 장비 단계는 제거했으며 그룹 창 내부 장비 탭은 그대로 유지합니다. 상세 창 제목은 RF, FPGA, CCD 등 그룹 이름만 표시합니다. Rabi population의 수집 중/최종 그래프에는 grid를 표시합니다.

SPAM의 수집 중/종료 그래프는 같은 표시 방식을 사용합니다. successes/attempts 그래프는 제거했으며 원시 통계 저장은 유지합니다. Histogram은 정규화 확률이 아닌 누적 발생 횟수로 표시합니다. SPAM error Y축은 현재 오류율의 최소·최대에 여백을 더해 자동 조정합니다.
