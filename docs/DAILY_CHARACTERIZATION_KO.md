# Daily characterization — Fluorescence / microwave Rabi

FPGA 창에서 `fpga_local` 옆의 `Daily characterization`을 엽니다. FPGA는 기존 창에서 한 번만 연결합니다. 새 COM 연결을 만들지 않습니다. Fluorescence는 PMT만 읽고, Rabi는 아래 설명대로 microwave 및 선택 FPGA 출력을 제어합니다.

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

## Microwave Rabi

### apsyn420_mw 연결

기존 AnaPico APSYN420 GUI/API를 사용합니다. `config/devices/anapico/device_config.yml`에 `apsyn420_mw` 이름을 추가했으므로 RF → AnaPico 상세 창에 표시됩니다. 서버에 이미 등록되어 있으면 서버 드라이버/YAML을 교체할 필요가 없습니다. GUI가 사용하는 서버의 APSYN420 드라이버는 기존 `frequency`, `output`, `identity` 파라미터와 호환되어야 합니다. 서버 실연결은 이번 검증에 포함되지 않았습니다.

기존 개인 장비 구성 파일은 자동 덮어쓰지 않습니다. 메인 Configuration 편집에서 **직접 추가** 또는 서버 조회 후 추가로 아래 항목을 사용 설정하고 저장한 뒤 RF 그룹을 연결하세요.

```json
{"family":"anapico","name":"apsyn420_mw","group":"RF","enabled":true}
```

새 장비 구성의 기본 목록에는 포함됩니다. 별도 IP나 TCP socket을 Rabi에서 열지 않고 기존 InstrumentServer 연결을 사용합니다. 기존 APSYN420 GUI와 같이 power setpoint는 추가하지 않습니다. reference 설정도 자동 변경하지 않습니다.

### EA Rabi / EC Rabi

두 탭에 조건·매핑 불러오기, 저장, 개별 Run/Stop, 결과 폴더, 이전 결과 열기가 있습니다. 기본값은 기존 코드의 12,642,820,855 Hz, 10 us 시간 간격, 0부터 10개 시간점, 점당 500 shots, threshold 2입니다. frequency start=end이면 단일 주파수 시간 scan이고, end와 step을 설정하면 주파수 scan도 수행합니다. 끝점은 정수 step에 맞아야 합니다.

- EA: PMTFA, AOMA, MW_A, EOM_7GA1, EOM_7GA2, EOM_2GA
- EC: PMTFC, AOMC, MW_C, EOM_7GC1, EOM_7GC2, EOM_2GC

모든 역할은 각 Rabi 탭에서 변경 가능합니다. 냉각 시간·반복, AOM wait, 초기화, 검출 시간, microwave pulse step, pulse points, shots, threshold, 주파수 정착 시간, 점당 timeout을 설정합니다. GUI 시간은 us, JSON의 T_* 및 WAIT_AOM은 원본과 같은 10 ns clock 정수입니다. 원본 memory 구조 때문에 shots는 최대 1024, 전체 shots는 2,000,000으로 제한합니다.

실행은 선택 FPGA 출력을 cooling 상태로 설정하고 MW gate를 LOW로 만든 후 AnaPico 주파수 설정/출력 ON → 정착 대기 → 원본의 냉각·초기화·MW pulse·PMT 검출 순서로 진행합니다. AOM/EOM/MW는 선택한 역할만 제어하며 오븐·셔터는 조작하지 않습니다. fluorescence와 달리 Rabi는 AOM/EOM을 실제로 조작합니다.

정상 종료·Stop·실패 시 **AnaPico OFF**를 시도하고, 별도 취소되지 않은 정리 경로로 MW LOW, PMT counter OFF, EOM_2G LOW, 선택 AOM/EOM_7G_1/2 HIGH(cooling)를 수행합니다. 시작 전 상태로 복원하는 동작은 아닙니다. OFF 실패여도 FPGA 정리를 별도로 시도하며 정리 실패를 명확히 기록합니다. 통신이 끊긴 상태에서 물리적 종료를 보장하지 않습니다. 같은 FPGA 및 microwave의 다른 작업은 실행 동안 거부됩니다.

### 결과와 원본 대비 차이

각 시간점의 population을 해당 EA/EC 탭에 표시하고, 종료 후 photon histogram, pulse time vs bright population(+fit), microwave frequency vs 원본 지표 `(1+max(population)-min(population))/2` 및 Rabi frequency(오른쪽 축)를 표시합니다. 일반 contrast `max-min`도 분석 파일에 함께 저장합니다. 피팅 결과의 Rabi frequency와 π time은 주파수별로 위쪽에 표시합니다.

원본의 `counts >= threshold` bright 비율 및 `A*sin(pi*f*t)^2+C` 모델을 유지합니다. count를 39로 자르던 원본 처리는 제거하여 raw counts를 그대로 보존합니다. 0-count 임의 보충도 없습니다. 피팅에는 여러 초기값과 Nyquist 범위 제한을 사용하며 실패 시 원본처럼 초기 추정값을 피팅 결과로 내보내지 않습니다. 유한한 피팅 결과도 충분한 시간점·진동 주기 및 배경 검증이 필요합니다. 시간축은 원본 pulse-step 기준의 명목 시간이며 기존 wait/branch 보정(-7 clocks)은 유지합니다. 별도의 X_control로 시간축을 다르게 지정하지 않습니다.

`configuration.json`, `raw_fifo.csv`, `points.json`, `population.csv`, `analysis.json`, `analysis.png`, `result.json`을 실행별로 저장합니다. 미완료 시간점의 수신 데이터는 raw_fifo.csv에 남고, 완전한 시간점만 population/fit에 사용합니다. 부분 결과는 cancelled/failed로 표시됩니다. 결과가 없거나 fit이 불가능하면 성공 수치로 표시하지 않습니다.

```python
def main(devices):
    fpga = devices.fpga("fpga_local")
    microwave = devices.anapico("apsyn420_mw")
    ea = fpga.run_rabi("EA", microwave).wait()
    ec = fpga.run_rabi("EC", microwave).wait()
```

`settings=...`, `settings_file=...`, `directory=...`를 지정할 수 있습니다. microwave 인자는 명시한 AnaPico API이며 설정의 microwave 이름과 일치해야 합니다. `stop_rabi()` 또는 handle.request_cancel()로 중단합니다. 메인/Daily 어느 workflow에서 호출해도 같은 EA/EC 결과 탭으로 전달됩니다. 예제는 `labremote/workflow/daily_rabi.py`입니다. Daily Workflow 편집기의 불러오기로 선택하면 됩니다.
