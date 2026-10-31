# CCD 이온 포획 → 오븐 종료 → FPGA 파일 실행

## 이온 검출 후 오븐 종료

먼저 CCD 탭에서 실제 Thorcam과 oven_psu / oven_relays를 연결합니다.
workflow에서 `load_one_ion.py`를 열어 실행합니다.

```python
def main(devices):
    result = devices.ccd().load_oven(
        isotope=171, shutter='shutter_2',
        threshold=1000, min_area=3, target=1, consecutive_frames=3,
    ).wait()
    print(result)
```

현재 target=1은 검출된 이온이 **1개 이상**이라는 뜻입니다. 정확히 1개만
허용하는 조건이 아닙니다. threshold/min_area/ROI는 실제 CCD 영상에 맞추세요.
새 프레임 3개 연속 검출 시 0.15 A 단계 하강 → 출력 OFF → 셔터 CLOSED를
확인한 뒤 반환합니다. 600초 timeout, 사용자 취소, 통신 오류에는 정리를 시도하고
예외를 전달하므로 다음 작업으로 진행하지 않습니다. timeout은 종료 시작 시점이며
하강·통신 시간은 추가됩니다. 통신 불량 시 물리적 OFF가 확인되지 않을 수 있습니다.
이 API는 오븐 로딩 시작부터 종료까지 관리합니다. 이미 다른 방식으로 켠 오븐을
단순히 감시하는 API와는 다릅니다.

## 특정 시퀀서 파일 실행

FPGA는 현재 구조대로 **UI PC에 연결된 로컬 시리얼 FPGA**를 사용합니다.
먼저 FPGA 탭에서 fpga_local을 연결하고 반복 측정/모터 스캔을 종료하세요.
파일 경로도 서버 PC가 아닌 UI PC의 절대 경로입니다.

```python
def main(devices):
    result = devices.fpga('fpga_local').run_sequence_file(
        r'D:\sequences\my_sequence.py',
        parameters={'channel': 0, 'exposure_ms': 100},
        timeout_s=10, max_rows=16,
    ).wait()
    print(result['rows'])
```

프로그램 파일은 `build_program(parameters)`가 bundled SequencerProgram을
반환하는 형식입니다. 예제는 `labremote/sequence_examples/pmt_exposure.py`입니다.

```python
from labremote.devices.fpga.controller import exposure_program

def build_program(parameters):
    program, _ = exposure_program(parameters['channel'], parameters['exposure_ms'])
    return program
```

사용자 고유 코드에서는 `labremote.devices.fpga.vendor.SequencerProgram_v1_08`
의 SequencerProgram/reg를 import하여 구성하고 마지막에 `stop()`을 추가합니다.
파일 안에서 새 시리얼 포트를 열거나 `program(target=...)`, `start_sequencer()`를
호출하지 마세요. 기존 standalone 실행 스크립트는 빌더 함수로 옮겨야 합니다.
`__main__` 블록은 실행하지 않지만 Python 파일의 다른 최상위 코드는 실행됩니다.
사용자가 신뢰하는 로컬 코드만 지정해야 하며, 샌드박스가 아닙니다.
다른 모듈은 정상적인 Python package import로 참조하세요. 파일 옆 디렉터리를
임의로 sys.path에 추가하지 않습니다. build_program은 짧게 프로그램만 생성해야 합니다.

실행은 기존 operation 큐/연결을 사용합니다. 정상 결과는 path, sha256, rows,
stopped를 포함합니다. 실행 전 이전 FIFO 결과를 비우고, 실행 중 FIFO를 읽어
max_rows로 메모리 사용을 제한합니다. PMT 예제 결과 행은
`[channel, exposure_ticks, count, 10]`입니다. 사용자 프로그램은 자체 행 형식을 사용합니다.

timeout_s는 업로드 후 FPGA 실행/결과 수집 제한입니다. 파일 Python 실행이나
업로드, 개별 시리얼 I/O의 시간은 포함하지 않습니다. 취소/timeout/결과 초과 때
STOP 명령과 정지 상태 확인을 시도합니다. 정지 실패는 별도 오류로 표시합니다.
STOP은 외부 TTL/레이저 출력의 원상복구를 의미하지 않습니다. 사용자 프로그램의
정상 종료 출력과 중단 시 필요한 하드웨어 처리를 별도로 설계해야 합니다.
실패한 요청을 자동 재시도하지 않으며 단순 결과 재조회로 다시 실행하지 않습니다.

## 예제 파일

- `labremote/workflow/load_one_ion.py`: 이온 검출 후 오븐 종료
- `labremote/workflow/run_fpga_sequence_file.py`: 지정 파일 실행
- `labremote/workflow/load_one_ion_then_fpga.py`: 종료 확인 후 파일 실행
- `labremote/sequence_examples/pmt_exposure.py`: 시퀀서 빌더 예제

세 workflow는 기존 workflow 탭 파일 목록에서 선택합니다. 경로/파라미터 수정 후 실행하세요.
이온 포획 후 오븐 종료가 실패하거나 timeout이 나면 결합 예제는 FPGA를 시작하지 않습니다.
이 변경은 UI PC에만 적용합니다. 기존 오븐/플리퍼 서버 파일은 변경하지 않습니다.
