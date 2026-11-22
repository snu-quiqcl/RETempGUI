# 설정 파일

설정은 모두 PC별 labremote/config 아래에 보관하며 이 디렉터리 전체는 Git에서 제외합니다.
일반 파일 하나를 읽고 같은 파일에 저장합니다. 기본 파일과 .local 파일의 덮어쓰기 구조는 사용하지 않습니다.

| 항목 | 기준 파일 |
|---|---|
| 서버 접속 주소 | devices/connections.json |
| 메인 UI·카메라 옵션·선택한 장비 구성 | ui/client_settings.json |
| 장비 구성 | ui/equipment.json |
| DAC 매핑·기본 전압·보정값 | devices/dac/EA.json, EC.json |
| DAC 탭·타이밍·프리셋 폴더 | ui/dac_dac_ea.json, dac_dac_ec.json |
| DAC 전압 프리셋 | presets/dac/EA/, EC/ |
| Oven 챔버·PSU/relay 이름·셔터·시간·전압·전류·ramp/OFF 조건 | operations/oven.json |
| Flipper 방향 별명·이미지 | ui/flipper_display.json |
| Flipper 경로·자동 전환 | operations/flipper_routes.json |
| Two-RF 설정 | operations/micromotion/EA.two_rf.json, EC.two_rf.json |
| FPGA 보드·포트·registry | devices/fpga/<device_id>.json, ports.json, registry.json |
| FPGA별 실험 설정 | devices/fpga/settings/<device_id>/ |
| 탭별 마지막 편집 상태 | ui/tabs/**/*.json |

Oven의 profiles는 EA_171, EA_174, EC_171, EC_174별 [전압 V, 전류 A]입니다.
power에는 ramp_step_a, ramp_interval_s와 off_* 조건을 둡니다.
Oven 화면에서 셔터/timeout 등을 저장해도 profiles와 power는 보존합니다.
Oven 서버 장비 이름은 operations/oven.json에서 지정하며 장비 구성 화면에서는 그 이름을 사용합니다.
Flipper 별명 변경은 별명 / 이미지 새로고침으로 반영합니다. 다른 파일은 앱 종료 후 수정하고 다시 실행합니다.

## 다른 PC 업데이트

1. 앱을 종료하고 기존 config 전체를 저장소 밖으로 백업합니다.
2. 코드만 업데이트합니다. config를 다른 PC의 값으로 덮어쓰지 않습니다.
3. 저장소 루트에서 python -B -m labremote.configuration.migration 으로 통합 계획을 봅니다.
4. python -B -m labremote.configuration.migration --apply --backup D:/coding/QCODES/RETempGUI-local-backups/<새폴더> 를 실행합니다.
5. 이 명령은 원본을 해시 검증하여 백업하고, 기존 override 값을 보존한 다음 통합된 파일을 검증한 뒤 이전 파일을 제거합니다.
6. 다시 실행하여 접속 주소·DAC·Oven 값을 확인합니다. 장비 연결/출력은 이 이전 작업에서 수행하지 않습니다.

이전 이름은 migration 모듈에서만 이전 대상으로 다룹니다. 앱 시작 중에 파일을 임의로 이동하지 않습니다.
