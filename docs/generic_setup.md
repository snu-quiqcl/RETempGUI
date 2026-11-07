# 범용 Setup

Queue에서 Workflow 추가 → `labremote/workflow/setup.py`를 선택한다.
장비 · 파라미터 설정 탭에서 **설정 추가 → 연결 장비 → 파라미터 → 값**을 선택한다.
각 행은 독립적인 요청이며 같은 장비를 여러 번 선택할 수 있다.
삭제·위·아래로 순서를 편집하고 전체 설정 후 대기 시간을 지정한다.
단위는 등록된 파라미터의 단위(예: Hz, dBm)를 사용한다.

이름을 `re_setup`으로 저장한 뒤 같은 setup.py를 다시 추가하여 이름을 `spam_setup`으로 지정하면 된다.
두 항목은 같은 Python 소스를 사용하지만 parameters의 설정 목록은 서로 독립적이다.
`docs/examples/setup_paths.queue.json`에는 이 두 항목이 들어 있다.
`docs/examples/re_ion_spam.queue.json`의 setup 항목도 범용 setup.py로 갱신했다.
예제는 장비 이름을 확인한 뒤 사용하며, 실험 threshold 등은 사용자가 정한다.

## 동작

- 편집은 장비 통신을 하지 않는다. 연결 목록은 GUI의 bindings에서 받는다.
- 연결이 끊긴 저장 항목은 '연결 안 됨'으로 남기며 다른 장비를 임의 선택하지 않는다.
- 장비 목록에는 연결 장비를 표시한다. 아직 Setup adapter가 없는 장비는 파라미터를 추가할 수 없다는 안내를 표시한다.
- 적용은 Queue 항목만 저장한다. 실행 시 설정값을 검증하고 설정에 나열된 장비를 확인한 뒤 위에서 아래 순서대로 기존 API를 호출한다.
- 각 요청의 완료를 기다린다. 기존 Worker FIFO, RF ramp 및 파라미터 readback 정책을 그대로 사용한다.
- 중간 실패는 다음 행을 중단한다. 결과의 completed에 완료 행, failed에 실패 행을 기록한다. 자동 rollback은 하지 않는다.
- Queue 전역 예약 정책은 이번 변경 범위가 아니다. 기존 예약 정책은 그대로다.

## 현재 연결된 설정 API

| 종류 | 제공하는 설정 |
|---|---|
| FPGA | HardwareDefinition의 디지털 출력 ON/OFF |
| Flipper | position 1/2 |
| Windfreak | A/B frequency, power, phase, output |
| SG384 | frequency, phase, BNC/N power·output |
| AnaPico | frequency, phase, output |
| DDS4 | 채널 1–4 frequency, phase, VVA, output |
| Thermotek | temperature setpoint |
| MDT | X/Y/Z voltage, master scan |
| Keithley | 채널 1–3 voltage/current, voltage limit/state, output |

이 목록은 `runtime/setup_workflow.py`의 adapter 목록이다. 읽기 전용 파라미터와 임의 명령은 노출하지 않는다.
OSA·오실로스코프·DAC·모터·CCD의 전용 동작은 아직 이 목록에 연결하지 않았다. 해당 장비의 모든 writable 파라미터를 무조건 raw set으로 우회하지 않는다.

## 설정 구조

setup.py는 `WORKFLOW_UI = {'editor': 'setup'}`을 명시한다.
편집창은 실행하지 않고 AST의 literal만 읽어 편집기를 고른다. 새 setup 항목은 빈 설정 목록으로 시작한다.
`queue_profiles.py`는 제거했으며 실행 시 기본값을 주입하지 않는다.
RE/Ion Check/SPAM도 editor 종류를 workflow에서 명시한다. 새 측정 항목의 설정은 기존 저장 설정에서 읽어 Queue에 사본으로 저장한다.
이전 frozen Queue의 RE/Ion/SPAM 편집기 선택은 호환용 파일명 경로를 남겼다.
기존 re_setup.py/spam_setup.py 항목을 편집하면 이전 설정을 변환했다는 안내가 표시된다. 적용할 때 setup.py로 저장하며 취소하면 원본은 유지한다.
사용자가 직접 수정한 옛 setup 소스를 유지하려면 변환을 취소하고 별도 이름의 workflow로 사용한다.
