# RE / Ion Check / SPAM Queue workflows

Queue에서 아래 파일을 순서대로 추가하고 **다섯 항목 전체를 하나의 Repeat group**으로 묶습니다.

1. `labremote/workflow/re_setup.py`
2. `labremote/workflow/ion_checks.py`
3. `labremote/workflow/re.py`
4. `labremote/workflow/spam_setup.py`
5. `labremote/workflow/spam.py`

`docs/examples/re_ion_spam.queue.json`을 Queue 불러오기에서 열어도 됩니다. 기본 예제는 ZZ, 그룹 1회입니다. 원하는 반복 횟수로 바꾸세요. 각도별 그룹 생성도 새 re.py를 인식합니다.

## 설정

새 workflow를 추가하면 편집 창의 parameters에 저장된 실험 설정 사본이 채워집니다. Ion Check는 `ion_check.local.json`(없으면 기본값), RE는 저장된 Entanglement 설정, SPAM은 EA/EC 저장된 SPAM 설정을 읽습니다. 편집 창에서 적용해야 Queue 항목에 저장됩니다. 실행 중 다른 설정 파일의 변경을 따라가지 않습니다. re.py는 기존 얽힘 설정 폼을 사용합니다. 다른 네 파일은 JSON 편집을 사용합니다.

Ion Check의 threshold_a/b/c는 반드시 실제 측정으로 정한 값으로 지정하세요. 미설정이면 측정 전에 실패하며 RE로 넘어가지 않습니다. mapping은 FPGA 이름(PMTA/PMTC/PMTFA/PMTFC, AOMA/AOMB/AOMC/AOMM)을 사용합니다. Ion Check 탭의 드롭다운에서도 jb/jc 핀 번호는 표시하지 않습니다. Queue의 설정 사본은 탭을 수정한다고 자동 변경되지 않습니다.

re_setup parameters:
```json
{
  "fpga": "fpga_local",
  "settle_s": 1.0,
  "flippers": {
    "EC_MIRA": "EC_MIRA",
    "EA_MIRA": "EA_MIRA",
    "ec_pmt": "ec_pmt",
    "ea_pmt": "ea_pmt"
  }
}
```

flippers의 값은 서버에 등록된 실제 장비 이름이며 대소문자를 구분합니다. 이름이 다르면 값만 수정하세요. 네 장비 모두 먼저 연결해야 합니다. workflow는 모든 대상 장비를 확인한 뒤 CCD_EC OFF, CCD_EA ON을 적용하고 EC_MIRA=1, EA_MIRA=1, ec_pmt=1, ea_pmt=2로 순차 이동합니다. 이동마다 position을 읽어 요청값과 비교합니다. 마지막에 settle_s만큼 기다립니다. 기본 1초는 추가 안정화 대기이며 장비의 실제 기계 응답에 맞게 조정하세요.

spam_setup은 CCD_EA OFF 후 CCD_EC ON을 적용하고 settle_s만큼 기다립니다. 플리퍼 위치는 변경하지 않습니다. 두 setup 모두 DAC나 RF/MW 주파수·출력을 설정하지 않습니다. CCD 출력은 slow port이므로 명령 완료를 확인하며 물리 출력 상태를 readback했다는 의미는 아닙니다. Setup 도중 오류가 나면 이후 측정을 진행하지 않습니다.

## 순서 검토

- Ion Check → RE: B가 어둡고 A/C가 밝아야 통과합니다. DAC swap은 여전히 미구현입니다. 비정상 판정은 최대 N회 재측정 후 Queue를 중단합니다.
- RE 자체의 시퀀스는 batch 시작에 CCD_EC=0/CCD_EA=1을 설정하고 herald 후 fluorescence 검출 경로로 전환합니다. 종료/cleanup도 CCD_EC=1/CCD_EA=0입니다. spam_setup은 이 상태를 SPAM 전에 명시적으로 다시 맞춥니다.
- SPAM은 EA 후 EC 순서로 측정합니다. 두 챔버 설정을 모두 검증한 뒤 시작하며 한쪽이 실패하면 이어서 진행하지 않습니다.
- 반복 시 re_setup을 생략하면 이전 SPAM의 광로 상태로 Ion Check가 시작될 수 있으므로 다섯 항목 전체를 반복하세요.
- RE 광로에서 Ion Check에 선택한 PMT로 실제 fluorescence가 들어오는지는 물리 배선에 따라 확인해야 합니다. PMTA/PMTC와 PMTFA/PMTFC는 자동으로 광로에 맞춰 바뀌지 않습니다.
- MW 주파수/출력은 외부에서 준비해야 합니다. 요청된 setup에는 RF 설정이 없습니다.
- 모니터는 ion_checks/re/spam의 측정 종류를 자동 인식하며 setup은 일반 상태 항목으로 표시합니다.

이 예제는 실행 순서와 연결 구조를 검증하기 위한 것입니다. 실제 장비 동작은 실행하지 않았습니다.
