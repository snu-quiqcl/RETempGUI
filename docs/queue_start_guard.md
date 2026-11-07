# Queue와 장비 Worker의 실행 소유권

Queue 시작 시 전체 연결 장비를 검사하는 `queue_start_guard`는 제거했다.
Queue는 workflow 실행 순서, 반복, 결과, 취소만 관리한다.
workflow_session도 전역 실행 잠금 대신 실행 식별자를 전달한다.

## 장비별 처리

- 각 DeviceWorker는 기존 FIFO와 독립 스레드로 명령을 실행한다.
- workflow가 실제로 사용하는 장비만 Worker에서 예약한다. 다른 실행의 같은 장비 접근은 장비명과 점유 실행을 포함한 ResourceBusy로 거절한다.
- Queue는 단계 사이에 설정이 바뀌지 않도록 사용한 장비의 예약을 Queue 종료까지 유지한다. 중지/실패 시에도 정리 후 해제한다. Queue 일시정지 중에는 유지한다.
- standalone workflow는 완료까지 유지한다. WorkflowGroup을 직접 만드는 코드는 반드시 finish()를 호출해야 한다.
- 물리 장비 주소를 정규화한 공유 장부는 중복 이름으로 연결한 동일 장비를 보호한다. 장부 잠금은 예약 갱신에만 쓰며, I/O나 실험 전체를 직렬화하지 않는다.
- 모터 스캔은 기존처럼 FPGA의 원자적 MEASURE를 공유하고 각 모터는 독점한다. PID는 제어하는 MDT를 예약하며 OSA의 캐시 피드백만 읽는다.

## 자동 모니터링

실험이 사용하지 않는 장비의 자동 조회와 반복 모니터링은 계속 실행한다.
사용 중인 장비의 자동 조회는 보류하고 해제 후 재개한다. 주기적 요청은 장비별 하나로 합쳐서 누적되지 않는다.
이미 실행 중인 자동 조회는 해당 Worker FIFO에서 끝난 뒤 실험 명령이 실행된다.
서버별 자동 조회 간격과 타임아웃 차단은 그대로 유지한다.
모터 스캔 화면과 DAC 화면의 주기적 상태 조회도 AutoMonitor를 사용한다.

OSA spectrum/Thermotek telemetry 같은 명시적 반복 작업은 매 회차 완료 후 다음 요청을 낸다.
다른 장비의 Queue 때문에 중지하지 않는다. 같은 장비를 독점해야 하는 workflow가 시작되면 해당 Worker가 충돌을 보고한다.
일반 수동 명령은 standalone 반복 조회 사이에 실행할 수 있다.

## 검증

`tests/test_worker_queue_concurrency.py`는 실제 QueueRunner, RE runner, Worker 스레드와 FIFO를 사용하고 장비 응답만 가짜로 대체한다.

- OSA spectrum + Thermotek telemetry + RF 자동 조회와 RE Queue 2회 반복 동시 실행
- 반복적인 전체 parameter scan 중 RE 완료
- 같은 FPGA 자동 조회의 보류/재개와 대기열 크기 제한
- 이미 실행 중인 자동 조회가 끝난 뒤 RE 실행
- 같은 장비 충돌, 다른 장비 독립 실행, 같은 물리 장비 alias 보호
- Queue 단계 사이 예약 유지, 실패 후 해제, Queue 취소 시 OSA 반복 작업 유지

관련 Queue/RE/Ion Check/SPAM/자동 조회/반복 측정/PID/스캔/micromotion/runtime 테스트: 170개 통과, 1개 제외.
제외한 전체 창 테스트는 검증 환경에 pyqtgraph가 없어서 실행하지 못했다.
실제 장비 접속은 검증 harness에서 차단했다. 원격 서버의 실제 응답 지연과 하드웨어 동시성은 실장비에서 별도 확인해야 한다.
