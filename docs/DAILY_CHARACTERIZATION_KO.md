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

Rabi는 외부에서 설정된 microwave 상태를 유지하면서 FPGA 펄스 시간만 스캔하는 operation입니다. **주파수 설정, RF 출력 ON/OFF, 주파수 정착 대기는 operation 외부에서 관리합니다.** Rabi 내부에는 주파수 loop나 AnaPico API 호출이 없습니다. Ramsey/SPAM은 아직 구현되지 않았으며 이후 같은 책임 분리를 적용합니다.

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
