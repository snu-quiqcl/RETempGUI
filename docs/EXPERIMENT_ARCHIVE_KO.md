# 실험 조건 라이브러리와 주파수별 Rabi 저장

## 원칙

실험 조건은 JSON recipe, 실행 데이터는 매번 새 폴더에 저장합니다. 같은 조건을 다시 실행해도 이전 측정은 덮어쓰지 않습니다. Rabi operation은 FPGA만 제어합니다. 주파수 변경은 외부 workflow에서 AnaPico API를 호출합니다. UI에는 가장 최근 Rabi 결과를 표시하며, 모든 주파수의 원시 데이터는 파일로 남습니다.

`labremote/config/operations/characterization/`의 실험별 JSON은 재사용할 수 있는 조건 템플릿입니다. 각 탭의 **다른 이름으로 저장**으로 조건·역할 매핑을 보관하고 **불러오기**로 재사용할 수 있습니다. 실행 폴더의 `configuration.json`은 그 실행에 실제 전달된 조건의 사본입니다. 저장 후 UI 조건을 바꿔도 기존 기록은 바뀌지 않습니다.

장비 전체의 물리적 상태를 자동으로 알 수 있는 것은 아닙니다. 예제는 MW frequency와 output만 읽고, FPGA 측정 조건과 역할 매핑을 저장합니다. 레이저 조건, RF power, reference, 자기장, 광학계 변경 등은 recipe의 `external_conditions`에 기록하세요. 값마다 단위와 `manual`/`measured` 등의 출처를 함께 기록하는 것을 권장합니다. 설정값과 readback은 구별해 보관합니다.

## UI에서 주파수 스캔 실행

1. FPGA와 `apsyn420_mw`를 연결합니다. MW power·reference·출력 ON은 기존 장비 창에서 설정합니다.
2. `rabi_frequency_sweep.json`을 같은 디렉토리에 `rabi_frequency_sweep.local.json`으로 복사합니다. 예제 주파수는 실제 실험에 맞게 변경하세요.
3. `frequencies_hz`, `settle_s`, 저장 `directory`, 장비 이름, `external_conditions`를 수정합니다. 저장 경로는 절대 경로를 권장합니다.
4. EA/EC Rabi 탭에서 저장한 JSON 객체 전체를 recipe의 `rabi_settings`에 넣습니다. `chamber`와 역할 매핑도 그 객체에 포함됩니다. 별도 조건 파일을 연결하려면 아래 Python 예제처럼 로드하세요.
5. 메인 또는 Daily Characterization의 Workflow에서 `labremote/workflow/rabi_frequency_archive.py`를 열어 실행합니다.

실행 순서는 `주파수 설정 → 안정화 대기 → MW frequency/output 읽기 → Rabi operation → 지점 기록`입니다. frequency는 Hz, settle은 초입니다. output이 OFF이면 측정하지 않고 실패 기록을 남깁니다. 정상 종료·Stop·실패 때도 MW 출력은 변경하지 않으며 주파수는 마지막 설정값에 남습니다. FPGA operation 자체의 정리는 기존과 같습니다.

## 저장 구조

```text
YYYYMMDD_HHMMSS_series_<UUID>/
  series.json                # 공통 recipe, 외부 조건, 각 지점 상태, 상대 경로, SHA256
  index.csv                  # 주파수/상태/결과 위치 요약
  workflow.py                # 실행 workflow 사본 (파일을 전달한 경우)
  source/                    # sequencer·hardware definition·operation·분석 코드 사본
  points/00000/
    microwave_readback.json  # 요청 주파수 / 읽은 주파수 / 출력 상태
    <timestamp>_Rabi_EA_<ID>/
      configuration.json     # 조건, 역할, FPGA 이름, HD 이름, 주파수 메타데이터
      raw_fifo.csv           # 수신 원시 값; 오류·중단 시 받은 부분도 보존
      points.json            # 수집된 pulse point별 counts
      population.csv         # pulse time, population, mean counts, error
      analysis.json
      analysis.png
      result.json            # completed / cancelled / failed, 오류, 완료 지점 수
  points/00001/...
```

초기화/중단 때문에 받지 못한 데이터는 0으로 채우지 않습니다. `raw_fifo.csv`의 `valid`는 형식/인덱스 검증 결과이며, 물리적 신호 품질 판정은 아닙니다. Rabi의 미완료 pulse point는 원시 FIFO에 남지만 `points.json`에는 완료된 point만 포함될 수 있습니다. 후처리에서는 `result.json` 상태와 완료 수를 확인하세요.

Stop/일반 예외는 부분 파일과 상태를 기록합니다. 강제 프로세스 종료·정전·디스크 고장은 정상 종료 저장을 보장할 수 없으며, `running` 상태가 남으면 중단된 실행으로 검토해야 합니다. 자동 이어찍기는 구현하지 않았습니다. 재실행은 새 series로 시작합니다. 결과 폴더 전체를 옮기면 index의 상대 경로는 유지됩니다. 결과 내부의 예전 절대 경로보다 series의 상대 `result` 경로를 사용하세요.

## API 사용

장비 API를 바꿀 필요 없이 파일 저장 라이브러리와 기존 operation을 조합합니다.

```python
from labremote.characterization import config, rabi
from labremote.workflow.rabi_frequency_archive import execute

def main(devices):
    recipe = config.read(config.ROOT / 'rabi_frequency_sweep.local.json')
    recipe['rabi_settings'] = rabi.load('EA', config.ROOT / 'rabi_EA.local.json')
    execute(devices, recipe, workflow_file=__file__)
```

직접 다른 실험을 묶을 때도 같은 보관 API를 쓸 수 있습니다.

```python
from labremote.characterization.archive import ExperimentArchive

def main(devices):
    fpga = devices.fpga('fpga_local')
    with ExperimentArchive('D:/ExperimentData', recipe={'experiment': 'initialization'}) as archive:
        point = archive.begin_point({'chamber': 'EA'})
        result = fpga.run_initialization('EA', directory=point).wait()
        archive.finish_point(point, result)
```

각 initialization 실행의 실제 settings는 자체 `configuration.json`에 저장됩니다. 여러 지점에서 같은 조건을 고정하려면 시작 전에 JSON을 한 번 읽고 `settings=...`로 넘기세요.

## 외부 분석 예시

```python
import json
from pathlib import Path
import pandas as pd

root = Path('D:/ExperimentData/실행폴더')
series = json.loads((root/'series.json').read_text(encoding='utf-8'))
frames = []
for point in series['points']:
    if point['status'] != 'completed':
        continue
    folder = (root/point['result']).parent
    frame = pd.read_csv(folder/'population.csv')
    frame['series_point'] = point['index']
    frames.append(frame)
table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
table.to_csv(root/'combined_population.csv', index=False)
```

`frequency_hz_metadata`는 이 예제에서는 실제 readback 값입니다. 개별 `run_rabi(..., frequency_hz=...)` 호출에서는 호출자가 제공한 메타데이터일 뿐, operation이 주파수를 읽거나 변경하지 않습니다. CSV/JSON을 사용하므로 별도 분석 도구에서 피팅 방법을 바꾸거나 raw counts로 다시 분석할 수 있습니다. pandas는 이 외부 분석 예시에만 필요하며 UI에 새 의존성을 추가하지 않았습니다.
