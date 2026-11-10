# Queue와 operation 단위 장비 실행

Queue는 순서, 반복, 결과, 취소를 관리한다. 전체 장비 사전검사나 단계 사이 장비 예약은 하지 않는다.
workflow_session / ExecutionOwner는 사용한 장비를 오류 진단용으로 기록할 뿐 잠그지 않는다.

## 실행 경계

- 각 장비 Worker가 독립 스레드와 FIFO를 가진다. Queue, built-in runner, PID, 반복 측정 모두 같은 API로 요청한다.
- OperationRunner는 callback 실행 전에 해당 물리 장비의 operation 소유권을 얻고, 정리와 오류 처리가 끝난 뒤 handle 완료를 알리기 전에 해제한다.
- FPGA의 RE, Ion Check, SPAM/Ramsey, Rabi 등은 업로드→실행→FIFO 수신→정리를 하나의 acquisition callback에서 수행한다. 취소도 그 callback의 cancellation token으로 전달한다.
- 같은 Worker의 다음 요청은 정리 완료까지 FIFO에서 대기한다. RE의 후처리/그림 저장이나 Queue 단계 사이에는 다른 요청을 처리할 수 있다.
- 정리 실패는 ConnectionError로 처리하여 연결을 사용 불가로 만들고 다음 요청을 막는다. FPGA timeout의 연결 정리도 operation 완료 전에 수행한다. 명시적으로 재연결해야 한다.
- 같은 물리 장비를 별도 Worker alias로 중복 연결하면 operation 소유권 검사가 동시 접근을 거절한다. 일반적인 단일 Worker 사용은 FIFO 대기한다.

## 모니터링과 PID

자동 조회는 서버 endpoint당 최대 한 건만 FIFO에 제출하고 주기적 요청을 합친다. 이미 실행 중인 operation 뒤에 한 건을 대기시킬 수 있으므로 PID처럼 요청이 잦아도 조회 기회가 생긴다. 제출된 조회는 FIFO 순서를 지킨다. 아직 대기 중인 foreground 요청이 있으면 새 자동 조회 제출을 보류한다. 서버별 조회 간격과 timeout 차단은 유지한다.

OSA spectrum과 Thermotek telemetry 반복은 매 요청 완료 후 다음 요청을 낸다. Queue 전체나 runner 전체를 예약하지 않는다.
PID는 MDT 읽기/보정 operation만 제출하고 OSA의 완료된 spectrum 캐시를 읽는다. GUI에서는 PID 제어 축의 수동 전압과 Master Scan 설정만 비활성화하며 다른 축과 읽기는 허용한다. 공통 파라미터 쓰기 경로에서도 동일 설정 충돌을 검사하므로 setup/workflow가 UI 제한을 우회하지 않는다.

동일 runner 중복 시작과 같은 모터를 사용하는 스캔 중복 실행은 계속 거절한다. 이는 설정/결과 상태가 덮어써지는 것을 막는 시작 조건이다. Micromotion의 DAC 서버 제어 lease와 oven의 CCD loading interlock도 별도 하드웨어 절차로 유지한다. Queue가 여러 장비의 설정을 단계 사이에 고정해 주지는 않는다.

## 검증

`tests/test_worker_queue_concurrency.py`는 실제 QueueRunner, RE runner, PID, Worker FIFO를 사용하고 장비 응답만 가짜로 제공한다.

- RE Queue 2회 반복 + OSA spectrum + Thermotek telemetry + MDT PID + RF 및 전체 장비 주기적 조회
- FPGA 정리 중 다음 요청 대기, 정리 실패 후 요청 차단
- RE 그림 저장 중 같은 FPGA 자동 조회 실행
- Queue 단계 사이 일반 요청 허용, 취소 시 다른 장비 반복 측정 유지
- 동일 장비 alias의 operation 충돌 검사

`test_operation_pid_controls.py`는 PID 축/다른 축의 UI 활성 상태와 종료 후 복구를 검증한다. 관련 Queue, RE, Ion Check, SPAM, 자동 조회, PID/스캔, acquisition 테스트도 함께 실행한다. 테스트 harness는 실제 transport 생성을 차단한다. 실장비 지연 및 서버 동시성 검증은 별도로 필요하다.
