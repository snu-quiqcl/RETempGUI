# Ion Check

GUI 재시작 후 FPGA 실험 창의 **Ion Check** 탭에서 사용합니다.

- **PMT 입력 1/2**: PMTA, PMTC, PMTFA, PMTFC 중 선택합니다. 두 입력은 합산하며 입력 2를 사용 안 함으로 설정하면 입력 1만 측정합니다. 같은 입력을 두 번 선택할 수 없습니다.
- **Laser A/B/C**: 각 역할에 사용할 AOM 출력을 선택합니다. FPGA 설정 이름(AOMA, AOMB, AOMC 등)으로 표시하며 jb/jc 핀 번호는 표시하지 않습니다. A/B/C는 서로 다른 출력을 선택해야 합니다. A 단계의 7GA, C 단계의 7GC 및 2G/MW OFF 제어는 기존 매핑을 유지합니다.
- **1회 측정**: B → A+7GA → C+7GC 순서로 측정합니다. 각 조건에서 선택한 PMT count를 합산하여 A/B/C 결과를 한 번에 받습니다. Threshold가 없어도 실행되며 이때 이온 판정은 미설정입니다.
- **최대 N회 판정 테스트**: 세 threshold를 모두 지정해야 합니다. N은 첫 측정을 포함합니다. B가 어둡고 A/C가 밝으면 즉시 성공합니다. 비정상이면 최대 N회까지 재측정하고 실패합니다. `자동 재확인 조건`은 이 재측정 횟수와 간격입니다. 1회 측정에는 N과 재측정 간격을 적용하지 않습니다.
- Ion Check 탭의 **Queue에 추가** 버튼은 제거했습니다. 기존 Queue 실행 경로는 유지합니다.
- 별도의 연속 반복 측정 기능은 없습니다. 재측정 간격은 유한 N회 workflow 내부에만 적용됩니다.

밝음은 `count >= threshold`입니다. 초기 threshold는 미설정이며 측정 데이터로 결정해야 합니다. Threshold 저장/불러오기와 결과 폴더 선택을 지원합니다.

통신·측정 완료와 이온 정상 판정은 별도로 표시됩니다. 정상 FIFO 수신만으로 workflow가 성공하지 않습니다. B가 밝으면 EA/EC swap 후보 또는 재확인으로, B가 어두우면서 A/C가 어두우면 ion loss 의심으로 표시합니다. **DAC 연결 여부와 관계없이 swap은 미구현이며 DAC 명령을 보내지 않습니다. DAC 구현 없이도 측정·판정·재측정이 가능합니다.**

종료·중단·오류 시 선택한 PMT counter를 끄고 선택한 A/C 출력 및 7GA/7GC를 켜며 선택한 B 출력과 2G/MW를 끕니다. 선택하지 않은 다른 AOM 출력에는 명령을 보내지 않습니다. 통신 실패로 정리하지 못하면 실패로 기록합니다. 정리 완료는 명령 실행 완료를 뜻하며 slow-port의 실제 출력 readback을 뜻하지 않습니다.

각 실행 폴더에 configuration.json, samples.json, result.json과 실행 소스 사본을 저장합니다. PMT 합계의 16-bit 덧셈 overflow는 오류로 처리합니다. 개별 PMT counter 자체의 wrap은 검출하지 않으므로 노출 시간을 충분히 짧게 설정해야 합니다.

설정 schema_version=2는 mapping을 포함하며 저장/불러오기에 적용됩니다. 기존 v1 설정은 PMTA+PMTC, AOMA/AOMB/AOMC 기본 매핑으로 읽습니다. `queue_ion_check.py`를 사용하는 기존 Queue도 호환됩니다. 탭에서 설정을 바꿔도 이미 저장된 Queue의 설정 사본은 바뀌지 않습니다. 더 오래된 frozen `ion_check_workflow.py`는 별도 구현이므로 이 탭의 매핑 변경을 적용받지 않습니다.

실제 FPGA/레이저 검증은 별도로 필요합니다. 자동 테스트는 모의 컨트롤러로 실행합니다.
