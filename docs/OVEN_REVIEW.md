# EC 오븐 로딩 검증 기록

실제 PSU·릴레이·CCD는 연결하거나 조작하지 않았습니다. 구현과 검증 범위는 [오븐 사용 안내](OVEN_LOADING_KO.md)를 참고하세요.

- 새 가짜 장비 테스트 19개 통과: 두 동위원소의 CH1 설정값, OFF 이전 route 금지, shutter open 이전 ON 금지, CH2/3 zero, 이온 검출 성공, 취소, workflow 취소, timeout, CCD 오류/끊김, 이중 시작 거부, Dummy 차단, 셔터 확인, 출력/셔터 종료 실패, 종료 대기, 가동 중 route 변경.
- 기존 runtime 19개, architecture 19개, workflow editor 11개, review regressions 32개, CCD 9개 통과. 합계 109개.
- Dummy CCD GUI: 기존 휠/가운데 버튼 확대, 영상 왼쪽·제어 오른쪽 배치, 숨긴 탭 이온 조건, 모든 worker 종료 확인.
- GUI 검사 최초 실행은 assertion과 worker 종료 확인 뒤 Qt 프로세스 종료 오류가 발생했습니다. 검증 스크립트에서 event filter·타이머·Qt 객체를 QApplication 생존 중 정리하도록 보완한 뒤 정상 종료했습니다.
- 오븐 동작은 동일한 operation runner, parameter registry, acquire/assign readback, FIFO device queue를 사용합니다. 측정과 이온 대기는 UI 스레드를 차단하지 않습니다.
- 물리적 EC 셔터 번호와 GPIO 동작, 실제 전류/전압, 네트워크 장애 때의 장비 상태는 현장에서 확인해야 합니다. 기본 shutter_2 선택은 물리적 확인을 대신하지 않습니다.

테스트 소스는 로컬 전용 `tests/test_oven_loading.py`에 보관합니다. Git 정책대로 tests 폴더는 업로드하지 않습니다. 서버 드라이버 원본, 실행 배치 파일, 로컬 IP 설정과 Git 기록은 이 기능 추가로 변경하지 않습니다.
