# Workflow Queue와 Queue Monitor

EA/EC 실험 탭과 기존 개별 실행은 그대로 사용합니다. 메인 창에는 Workflow 옆에 Queue와 Queue Monitor가 있습니다. 장비 설정과 실험 실행은 기존 `main(devices)` workflow가 담당하고 Queue는 순서·반복·실패 정책·실행 기록을 관리합니다.

## 사용 순서

1. 메인 창에서 필요한 장비를 연결합니다. 독립 실행 중인 측정은 끝내거나 중단합니다.
2. Queue에서 **Workflow 추가**로 Python workflow를 선택합니다.
3. 편집에서 이름, 작업 반복 횟수, 실패 정책 `stop` 또는 `skip`, JSON 변수를 설정합니다. 변수는 `devices.parameters`로 전달됩니다.
4. 위/아래 버튼으로 순서를 정하고 전체 목록 반복 횟수와 결과 저장 폴더를 지정합니다. 작업 A 2회, B 1회, 전체 2회이면 A,A,B,A,A,B 순서입니다.
5. Queue 저장으로 `*.local.json`에 보관합니다. 이 파일에는 workflow 소스와 변수가 포함되므로 장비 주소 등이 있으면 Git에 올리지 마세요. 결과 저장 폴더는 실행 컴퓨터에서 별도로 지정합니다.
6. Queue 실행을 누릅니다. Queue Monitor에서 단계별 상태·시간·실패 이유·반환된 숫자 지표를 확인합니다. 기존 EA/EC 결과 화면도 각 operation의 기존 신호 경로로 갱신됩니다.

`현재 작업 후 일시정지`는 workflow가 끝나고 다음 작업 직전에 멈춥니다. `계속`으로 재개합니다. `Queue 중단`과 메인 중단은 현재 workflow를 취소하고 정리 완료를 기다립니다. 취소를 확인하지 않는 임의 Python 루프나 블로킹 장비 호출은 강제 종료하지 않습니다. workflow의 대기는 `devices.wait(seconds)`를 사용하세요.

## Workflow 결과

기존 `main(devices)`가 반환값 없이 정상 종료하면 성공입니다. 등록된 operation의 완료도 기다립니다. 다음처럼 명시적으로 결과를 반환할 수 있습니다.

```python
def main(devices):
    # 기존 장비 API 및 FPGA operation 사용
    return {
        "status": "completed",  # completed / failed / cancelled
        "reason": "",
        "result_paths": [],     # 저장한 데이터 파일 또는 폴더
        "metrics": {"contrast": 0.91},
        "cleanup_status": "not_required",
        "continue_allowed": True,
    }
```

Python API `run_workflow`의 정상 반환값은 `WorkflowResult`입니다. 원래 반환 데이터는 `.value`에 남습니다. 예외는 기존처럼 호출자에게 전달하며 Queue가 실패 결과로 변환합니다. 독립 Workflow UI도 성공/실패 결과를 표시합니다.

`cleanup_status`는 `completed`, `not_required`, `not_reported`, `failed`, `unknown`을 지원합니다. 장비를 변경한 workflow의 정리 여부는 해당 workflow가 실제로 확인해서 기록해야 합니다. Queue가 모든 장비를 자동 초기화하거나 검증하지는 않습니다.

- `stop`: 실패한 작업 이후 실행하지 않습니다.
- `skip`: 일반 예외 또는 명시적 실패를 기록하고 다음 예정 실행으로 넘어갑니다. 같은 작업 반복이 남아 있으면 그 다음 반복부터 진행합니다.
- 통신 timeout/연결 오류, 종료 정리 오류, `continue_allowed=False`, `cleanup_status=failed/unknown`은 중단합니다.
- 사용자 취소와 `cancelled` 결과는 실패 정책과 무관하게 중단합니다.
- 실패한 작업은 다음 작업과 취소 토큰을 공유하지 않습니다. 다만 장비의 실제 상태는 자동 롤백하지 않습니다.
- 일부 실패를 넘기고 끝냈더라도 Queue 전체 결과는 `failed`입니다.
- 미실행 단계는 `cancelled`로 기록됩니다. 실패 작업의 자동 재시도는 없습니다.
- Queue 실행·일시정지 중 다른 독립 workflow/Queue는 실행을 거부하며 자동 장비 polling은 억제합니다. 수동 장비 제어는 기존 장비별 잠금 규칙을 사용하므로 Queue 실행 중 임의 변경은 피하세요.

## 저장과 재확인

기본 저장 위치는 프로젝트의 `data/queues`입니다. Queue 화면에서 변경할 수 있습니다. 실행마다 독립 폴더를 만듭니다.

```text
YYYYMMDD_HHMMSS_queue_<id>/
  queue_manifest.json
  steps/
    step_000001/
      workflow.py
      parameters.json
      workflow_result.json
      ... workflow가 저장한 실험 데이터
```

manifest에는 순서, 소스 SHA256, 반복 조건, 상태, 시간, 결과 경로, 실패 정보가 기록됩니다. `workflow_result.json`에는 예외 traceback도 남습니다. workflow는 `devices.run_directory` 아래에 결과를 저장하면 실행별로 분리됩니다. `devices.queue_context`에는 queue_id, step_id, iteration, job_repeat가 있습니다.

Queue에 추가한 Python 소스와 JSON 변수는 사본으로 고정됩니다. 편집의 **Python 소스를 현재 파일에서 다시 가져오기**를 선택해야 원본 변경이 반영됩니다. import한 모듈이나 workflow가 실행 중 읽는 외부 설정 파일까지 자동 복사하지는 않습니다. 재현에 필요한 설정은 변수에 담거나 기존 ExperimentArchive를 함께 사용하세요. 기존 operation 저장 형식은 유지됩니다.

Queue Monitor의 **저장된 Queue 열기**에서 `queue_manifest.json`을 선택하면 과거 결과를 확인할 수 있습니다. 현재 Queue 보기로 실시간 표시로 돌아옵니다. 숫자 metrics는 실행 단계별 그래프로 표시하며 선택한 단계의 상세 결과와 폴더를 열 수 있습니다. 이 화면은 공통 실행 모니터이며 이전 프로그램의 Remote Entanglement/IonSwap 전용 분석은 포함하지 않습니다. 저장된 실행의 중간 재개는 지원하지 않으며 구성을 다시 실행하면 새 기록을 만듭니다.

## 예시

- [queue_demo.py](../labremote/workflow/queue_demo.py): 장비 없이 확인. 변수 `{"value":1,"fail":false}`. 두 번째 작업에 `fail:true`, 정책 `skip`을 지정해 다음 작업 실행을 확인할 수 있습니다.
- [queue_rabi.py](../labremote/workflow/queue_rabi.py): `{"chamber":"EA"}`와 `{"chamber":"EC"}`로 각각 추가하세요. 선택적으로 `settings_file`, `settings`, `fpga`를 지정합니다. Microwave 주파수와 출력은 외부에서 설정하며 이 workflow는 FPGA Rabi operation만 실행합니다. 데이터는 단계 폴더 아래 `rabi`에 저장합니다.

주파수 변경 workflow → EA Rabi → EC Rabi처럼 구성하거나, 기존 주파수 sweep workflow 전체를 한 Queue 작업으로 추가할 수 있습니다. 조건 분기와 장비 정리는 workflow 내부에서 구현합니다.
