# 실험 중심 UI와 전체 장비 구성

## 메인 화면

- **메인**: Configuration 불러오기/편집/저장, 그룹별 연결, 전체 연결, 상세 제어창 열기.
- **Workflow**: 기존 Python `main(devices)` 편집/실행/중단 화면을 그대로 사용합니다.
- **Monitor**: 추후 구성을 위한 빈 화면입니다. 추가 장비 조회를 수행하지 않습니다.

RF, 미라, CCD, FPGA, 오실로스코프, 기타는 각각 별도 창으로 열립니다.
같은 버튼을 다시 누르면 기존 창을 앞으로 표시합니다. 창 닫기는 숨기기이며,
연결 해제나 촬영/작업 중지가 아닙니다. 메인 창 종료 시에는 기존 workflow 취소와
오븐 종료 정리를 기다린 뒤 worker와 모든 창을 종료합니다.
CCD 창을 숨겨도 기존 촬영과 이온 검출은 유지하고, 숨겨진 화면의 그리기만 생략합니다.

## 구성 파일

기본 개인 파일은 `labremote/config/ui/equipment.local.json`입니다.
공개 예제는 `labremote/config/ui/equipment.json`입니다.
개인 구성 파일은 `*.local.json`으로 저장하며 Git에서 제외됩니다.
다른 컴퓨터에서는 이 파일과 기존 로컬 하드웨어/카메라 설정을 직접 복사하세요.

```json
{
  "schema_version": 1,
  "name": "EC 실험",
  "devices": [
    {"family": "sg384", "name": "sg384_EC", "group": "RF", "enabled": true},
    {"family": "ccd", "name": "ccd_local", "group": "CCD", "enabled": true},
    {"family": "fpga", "name": "fpga_local", "group": "FPGA", "enabled": true}
  ]
}
```

- `family`: 기존 장비 종류. 편집 창의 선택 목록을 사용합니다.
- `name`: 기존 장비 이름. 모터는 기존 논리 이름을 유지하며 상세 화면의 Instrument 설정을 사용합니다.
- `group`: 메인 화면 그룹 연결 버튼에 포함될 그룹입니다. 상세 제어창의 장비 분류는 기존대로 유지합니다.
- `enabled`: 그룹/전체 연결 대상으로 사용할지 여부입니다.

장비별 `device_config.yml`, `parameter_registry.yml`, `labremote/config/devices/connections.local.json`,
오븐 설정, `labremote/config/operations/flipper_routes.local.json`, 카메라 및 FPGA 연결 옵션은 변경하지 않습니다.
RF/미라/모터/오븐/Flipper는 기존 메인 InstrumentServer 주소를 사용하고,
CCD와 FPGA는 기존 로컬 연결 방식을 사용합니다.

구성 파일은 **일괄 연결 대상 선택**입니다. 체크하지 않은 장비도 기존 상세 화면에서
직접 연결할 수 있으며, 연결된 장비는 기존처럼 workflow에서 사용할 수 있습니다.
이 기능이 workflow API, operation 순서/검증, 오븐 ramp/cleanup, CCD 검출 기준을 바꾸지 않습니다.

## 사용 순서

1. 메인의 **연결 설정 / 장비 목록**에서 기존 서버 주소를 확인하고 `Rescan server devices`를 실행합니다.
2. **Configuration → 편집**에서 사용할 장비를 체크합니다. 조회 장비 추가 또는 직접 추가도 가능합니다.
3. **구성 적용** 후 **저장**합니다. 여기까지 장비 연결이나 출력 변경은 하지 않습니다.
4. 그룹 **연결 / 재연결** 또는 **전체 연결**을 누릅니다. 연결 요청은 순서대로 제출합니다.
5. Workflow 탭에서 기존 실험 코드를 실행합니다. 수동 확인이 필요하면 상세 제어창을 엽니다.

기본 구성은 기존 장비 목록에서 만들며, 오븐 PSU/릴레이는 기본적으로 체크하지 않습니다.
사용하려면 `oven_psu` / `oven_relay` 항목을 체크하세요. Flipper는 서버에서 조회한 실제
이름을 `flip` 종류로 추가합니다. EA/EC 경로는 기존 Flipper 설정에서 지정합니다.

이미 정상 연결된 장비는 일괄 연결 시 건너뜁니다. 실패해도 다른 장비 연결을 계속하고,
재연결 버튼으로 실패/미연결 장비만 다시 시도합니다. 그룹 상태에 마우스를 올리면 장비별 상태를 볼 수 있습니다.
장비별 오류 메시지는 메인의 안내와 이벤트 로그에 표시됩니다.

실행 중이거나 연결된 장비가 있으면 구성 불러오기/적용을 막습니다. 기존 작업을 종료하고
연결을 해제한 뒤 구성을 바꾸세요. **연결 해제는 출력 OFF를 대신하지 않습니다.**
기존 종료 workflow를 먼저 수행해야 합니다. 메인의 작업 중단 버튼도 기존 작업 취소와
종료 정리를 요청하며 물리적 비상 정지 기능이 아닙니다.

마지막 구성 경로는 기존 `labremote/config/ui/client_settings.local.json`에 저장됩니다. 저장된 경로가 사라졌거나
구성 파일이 잘못되면 다른 구성으로 자동 연결하지 않고 빈 선택과 오류를 표시합니다.
개인 기본 파일이 처음부터 없는 경우에는 기존 목록으로 생성하며 자동 연결하지 않습니다.
