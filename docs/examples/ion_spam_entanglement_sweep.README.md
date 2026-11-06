# 이온 체크 → SPAM → 얽힘 예제 Queue

GUI 재시작 후 Experiment Queue → Queue 불러오기에서
`ion_spam_entanglement_sweep.queue.json`을 선택하세요.

구성은 ZZ, MW detuned 0°, 30°, …, 330°의 13개 그룹입니다.
각 그룹은 `[이온 체크 → SPAM(EA 다음 EC) → 얽힘]`을 N=3회 반복합니다.
전체 목록 반복은 1, 개별 workflow 반복은 1이며 총 117 workflow 실행입니다.
실패 정책은 모두 중단입니다. 이온 체크 자체의 max_attempts=3은 그룹 N과 별개입니다.

## 실행 전에 입력할 값

- 이온 체크 threshold_a/b/c는 실제 측정값이 없어 null로 저장했습니다.
  파일은 GUI에서 바로 열리지만, 값을 입력하지 않고 실행하면 첫 이온 체크에서
  측정 전에 중단됩니다. 아래 생성 스크립트를 사용하면 13개 그룹에 한 번에 반영됩니다.
- SPAM은 저장된 spam_EA.json / spam_EC.json 설정을 사본으로 포함합니다.
  PMT 역할도 기존 PMTFA/PMTFC 설정을 유지합니다. 이온 체크의 PMTA+PMTC 합산과는
  별도 측정 코드입니다. SPAM 검출 경로가 현재 셋업과 맞는지 확인하세요.
- 얽힘은 저장된 entanglement.local.json이 있으면 사용하고, 없으면 프로젝트 기본값을
  사용합니다. 각 그룹에서 basis와 phase_magnitude_deg만 변경합니다.
  기본값을 사용하는 경우 batches=100, detuning_hz=-2000 등도 그대로 포함됩니다.
  그룹 N은 이 내부 측정 횟수와 다릅니다.
- 장비 연결 및 RF/MW 주파수·출력 설정 workflow는 포함하지 않습니다.
  필요하면 그룹 앞에 추가하세요. 각도 값은 기존 얽힘 코드의 시간차 기반 phase
  magnitude이며 RF 장비의 set_phase 명령을 호출하지 않습니다.
- DAC swap 함수는 아직 미연결입니다. swap이 필요하면 재측정만 수행하며,
  정상 판정에 도달하지 못하면 Queue가 중단됩니다.

## N과 threshold를 한 번에 변경

프로젝트 Python 환경에서 `docs/examples/build_ion_spam_entanglement_queue.py`를 실행하세요.
옵션은 `--repeat N --threshold-a A --threshold-b B --threshold-c C`입니다.
A/B/C에는 exposure_us=1000에서의 실제 두 PMT 합산 count 기준 threshold를 넣습니다.
`--max-attempts`는 이온 체크 최대 측정 횟수, `--output`은 다른 저장 경로를 지정합니다.
생성 후 GUI에서 Queue를 다시 불러오세요. 기본 출력 파일은 이 예제 JSON이며 덮어씁니다.

GUI에서는 각 그룹 편집으로 N을 바꾸거나 자식 workflow 편집으로 parameters를 바꿀 수 있습니다.
Queue에는 Python 소스 사본이 저장됩니다. DAC 함수를 수정한 뒤에는 Queue를 다시 생성하거나
각 이온 체크 항목의 편집에서 Python 소스 다시 가져오기를 사용해야 합니다.
