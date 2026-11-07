# Ion Check

GUI 재시작 후 FPGA 실험 창의 **Ion Check** 탭에서 사용합니다.

- **1회 측정**: B → A+7GA → C+7GC 순서로 측정합니다. 각 조건에서 PMTA+PMTC를 합산하여 A/B/C count를 한 번에 받습니다. Threshold가 없어도 실행되며 이때 이온 판정은 미설정입니다.
- **최대 N회 workflow 테스트**: 세 threshold를 모두 지정해야 합니다. N은 첫 측정을 포함합니다. B가 어둡고 A/C가 밝으면 즉시 성공합니다. 비정상이면 최대 N회까지 재측정하고 실패합니다. 현재 DAC swap은 실행하지 않습니다.
- **Queue에 추가**: 현재 FPGA와 설정의 사본을 Queue 끝에 추가합니다. 이후 탭의 값을 바꿔도 추가한 항목은 바뀌지 않습니다. Queue에서 repeat group 안으로 이동하여 SPAM/얽힘 앞에 배치할 수 있습니다. 이온 판정 실패는 skip 정책과 관계없이 Queue를 중단합니다.
- 별도의 연속 반복 측정 기능은 없습니다. 재측정 간격은 유한 N회 workflow 내부에만 적용됩니다.

밝음은 `count >= threshold`입니다. 초기 threshold는 미설정이며 측정 데이터로 결정해야 합니다. Threshold 저장/불러오기와 결과 폴더 선택을 지원합니다.

통신·측정 완료와 이온 정상 판정은 별도로 표시됩니다. 정상 FIFO 수신만으로 workflow가 성공하지 않습니다. B가 밝으면 EA/EC swap 후보 또는 재확인으로, B가 어두우면서 A/C가 어두우면 ion loss 의심으로 표시합니다. DAC 미연결 상태에서는 판정과 재측정만 합니다.

종료·중단·오류 시 PMT counter를 끄고 A/C 및 7GA/7GC를 켜며 B/2G/MW를 끕니다. 통신 실패로 정리하지 못하면 실패로 기록합니다. 정리 완료는 명령 실행 완료를 뜻하며 slow-port의 실제 출력 readback을 뜻하지 않습니다.

각 실행 폴더에 configuration.json, samples.json, result.json과 실행 소스 사본을 저장합니다. PMT 합계의 16-bit 덧셈 overflow는 오류로 처리합니다. 개별 PMT counter 자체의 wrap은 검출하지 않으므로 노출 시간을 충분히 짧게 설정해야 합니다.

새 탭에서 추가한 Queue는 `labremote/workflow/queue_ion_check.py`와 공통 IonCheckRunner를 사용합니다. 기존에 저장한 Queue에는 이전 workflow 소스가 고정되어 있으므로 새 동작을 사용하려면 기존 Ion Check 항목을 이 탭에서 다시 추가하세요.

실제 FPGA/레이저 검증은 별도로 필요합니다. 자동 테스트는 모의 컨트롤러로 실행합니다.
