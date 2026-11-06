# Experiment Queue: Repeat Group

## 구성

1. 기존처럼 이온 체크 workflow, SPAM workflow, Entanglement 항목을 순서대로 추가합니다.
   Entanglement는 해당 탭의 Queue 추가 버튼으로 설정 사본과 함께 추가합니다.
2. 세 workflow 행을 Shift/Ctrl로 선택하고 **선택 항목 묶기**를 누릅니다.
3. 그룹 이름과 묶음 반복 N을 지정합니다. 자식 workflow 반복은 보통 1로 둡니다.
4. 그룹 편집에서 **얽힘 basis 적용 → ZZ**를 선택하면 그룹 내 기본
   `queue_entanglement.py` 항목의 저장된 설정을 ZZ로 변경합니다.
5. 그룹을 선택하고 **각도별 그룹 생성**에서 `0, 30, 60, ...`을 입력합니다.
   원본 그룹 바로 뒤에 MW detuned 각도별 복사본이 생성됩니다.
   그룹 반복 N, 이온 체크와 SPAM 설정은 복사되며 얽힘 설정의 basis와
   `phase_magnitude_deg`만 변경됩니다. 복사본의 workflow ID는 모두 새로 생성됩니다.
6. 전체 목록 반복은 보통 1로 둡니다. 장비 설정 workflow를 그룹 앞에 두면
   그 위치에서 한 번 실행됩니다. 전체 목록 반복을 늘리면 장비 설정도 다시 실행됩니다.

예:

```text
장비 설정
ZZ × N
    이온 체크 → SPAM → 얽힘(ZZ)
MW detuned 0° × N
    이온 체크 → SPAM → 얽힘(0°)
MW detuned 30° × N
    이온 체크 → SPAM → 얽힘(30°)
...
```

## 각도 설정 의미

각도별 생성은 기존 얽힘 측정의 `phase_magnitude_deg`를 설정합니다.
이는 MW detuning과 펄스 시작 시간차를 이용한 위상 설정이며, RF 장비의
set_phase 명령을 자동 호출하는 기능이 아닙니다. 주파수/출력 등의 장비 설정이
필요하면 그룹 앞에 별도의 설정 workflow를 둡니다. MW detuned 설정에는
0이 아닌 detuning이 필요하며, 기존 얽힘 설정 검증을 통과해야 합니다.

사용자 정의 얽힘 workflow에는 각도 자동 변경을 적용하지 않습니다.
그 경우 각 그룹의 자식 workflow 편집에서 JSON parameters를 직접 지정하세요.

## 편집 및 실패

- 그룹 또는 그룹 내 행을 선택하고 Workflow 추가를 누르면 그 그룹 끝에 추가됩니다.
- 그룹 밖에 추가 버튼은 선택 위치와 관계없이 최상위 목록 끝에 workflow를 추가합니다.
  위/아래 버튼으로 장비 설정 workflow를 원하는 그룹 앞에 배치할 수 있습니다.
- 그룹 행을 복제하면 자식과 설정도 복제합니다. 그룹 해제는 자식을 한 번씩의
  목록으로 되돌리며 그룹 반복 설정은 제거합니다.
- 위/아래는 같은 목록 내에서 이동합니다. 그룹 밖으로 이동하려면 해제 후 다시 묶습니다.
- 중첩 그룹은 지원하지 않습니다. 전체 실행 단계는 기존과 같이 최대 10,000개입니다.
- 그룹 실패 정책은 자식의 stop/skip보다 우선합니다.
  - Queue 중단: 실패 즉시 이후 실행 중단.
  - 현재 반복 건너뛰기: 해당 반복의 나머지 workflow를 skipped 처리하고
    다음 반복의 첫 workflow부터 실행. 마지막 반복이면 다음 그룹/항목으로 진행.
- continue_allowed=False, cleanup 실패/불명확, 연결/타임아웃 오류는
  건너뛰기 정책이어도 중단합니다. 이온 체크 workflow의 최종 실패도 여기에 해당합니다.
- 실패를 건너뛰고 이후 작업을 끝냈더라도 Queue 최종 상태는 failed로 남습니다.
- 일시정지는 기존처럼 현재 workflow 종료 후 적용됩니다. 재개 시 이미 완료된
  이온 체크를 자동 재실행하지 않습니다.

## 저장 및 결과

그룹 포함 Queue는 schema_version 2로 저장합니다. 기존 version 1 Queue도
그대로 불러오며, 그룹 없는 Queue는 version 1로 저장합니다.
이전 프로그램 버전은 version 2 Queue를 읽지 못합니다.

각 workflow의 소스/parameters 사본과 함께 `queue_context.json`을 저장합니다.
workflow에서는 `devices.queue_context`의 group_id, group_name,
group_iteration, group_repeat, iteration, job_repeat로 실행 위치를 확인할 수 있습니다.
Queue Monitor에도 그룹 이름과 반복 번호가 표시됩니다.
