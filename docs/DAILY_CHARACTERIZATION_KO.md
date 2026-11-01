# Daily characterization — Fluorescence

FPGA 창에서 `fpga_local` 옆의 `Daily characterization`을 엽니다. FPGA는 기존 창에서 한 번만 연결합니다. 새 COM 연결이나 RF/AOM/셔터 설정은 수행하지 않습니다.

## 화면

- **EA Fluorescence / EC Fluorescence**: 각각 변수 불러오기·저장, 개별 실행·중단, 이전 결과 열기, 시간 trace / histogram·Poisson / FFT 세 그래프를 제공합니다.
- **FPGA 역할 매핑**: 시퀀스의 PMT와 AOM을 현재 HardwareDefinition의 이름에 연결합니다. 기본값은 EA=`PMTFA`/`AOMA`, EC=`PMTFC`/`AOMC`입니다. PMT는 PMTA/PMTC/PMTFA/PMTFC 중 선택할 수 있습니다. AOMB/AOMM은 사용하지 않습니다.
- **Workflow**: 메인의 Workflow와 같은 위젯·실행 엔진입니다. 기본 예제는 EA 측정 완료 후 EC를 실행합니다. 실행 중지와 프로그램 종료도 기존 취소/종료 경로를 사용합니다.

역할 매핑 파일을 불러온 뒤 **저장 / 적용**을 누르면 이후 실행에 사용합니다. 다른 이름으로 저장은 파일 내보내기이며, 활성 매핑을 바꾸지 않습니다. 실행 시작 시 변수와 매핑을 복사해 고정합니다. 측정 중에는 매핑 적용을 막습니다. fluorescence 시퀀스는 PMT counter만 사용하므로 AOM 매핑을 바꿔도 이 실험에서 AOM 출력은 변경하지 않습니다. 미래 시퀀스에서는 `config.sequence_hardware(route)`의 `AOM_out` 및 `PMT_counter_*` 별칭을 사용할 수 있습니다. 공유 HardwareDefinition 전역은 변경하지 않습니다.

## 설정 파일

`labremote/config/operations/characterization/`에 공개 기본값을 둡니다.

- `fluorescence_EA.json`, `fluorescence_EC.json`
- `fpga_roles.json`

GUI의 변수 저장은 각각 `fluorescence_EA.local.json`, `fluorescence_EC.local.json`을 생성합니다. 매핑 저장 / 적용은 `fpga_roles.local.json`을 생성합니다. 로컬 파일이 있으면 기본값보다 우선하며 Git에서 제외됩니다. 다른 PC에서는 이 로컬 파일들을 별도로 복사하세요.

```json
{
  "schema_version": 1,
  "chamber": "EA",
  "exposure_ms": 0.5,
  "num_average": 500,
  "num_repeat": 20,
  "timeout_s": 60
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
    mapping_file="D:/lab/fpga_roles.local.json",
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
