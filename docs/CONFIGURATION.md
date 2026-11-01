# 설정 구조

설정은 `labremote/config` 아래 세 종류로 구분합니다. Python 로더는 config 루트에 남습니다.

| 위치 | 역할 |
| --- | --- |
| `devices/<장비종류>/device_config.yml` | 장비 연결 기본값, 출력 제한, 장비별 preset |
| `devices/connections.local.json` | 서버/모터 서버의 개인 네트워크 주소. 미설정 시 공개 `connections.json`의 빈 설정과 기존 localhost 기본값 사용 |
| `devices/fpga/ports.local.json` | FPGA별 마지막 성공 USB 포트 |
| `ui/defaults.json` | UI의 공개 초기값 |
| `ui/equipment.json` | 신규 실험 구성의 기본 항목. 장비 YAML의 이름과 기존 UI의 추가 이름을 함께 반영 |
| `ui/equipment.local.json` | 실제 사용할 장비, 그룹, 활성화 여부. 메인 Configuration에서 편집 |
| `ui/client_settings.local.json` | 마지막 UI 상태와 선택한 구성 파일 경로. 앱이 저장 |
| `ui/scan_*.local.json` | 탭별 마지막 scan 설정. 앱이 저장 |
| `operations/<장비종류>/parameter_registry.yml` | operation 파라미터의 읽기/쓰기/검증 정책 |
| `operations/<장비종류>/operation_config.yml` | RF ramp 또는 FPGA scan 기본값. 장비 설정과 합쳐 기존 API에 제공 |
| `operations/scan_roles.json` | 네 scan 탭 제목, X/Y/Z 모터 이름, PMT 선택 인덱스 |
| `operations/flipper_routes.json` | flipper 경로의 공개 기본값. 기본 자동 이동은 비활성 |
| `operations/flipper_routes.local.json` | 실제 서버 이름별 EA/EC 목표 위치와 자동 경로 사용 여부 |
| `operations/oven.local.json` | 기존 oven PSU/relay/shutter 선택값. 파일이 없으면 기존 기본값 사용 |

기존 example JSON 네 개는 실제로 읽는 공개 기본 파일로 통합했습니다. 동일 역할의 example을 별도로 유지하지 않습니다. 현재 메인 Configuration 편집기는 장비 사용 목록을 편집합니다. operation 경로 및 YAML은 파일로 편집하고 UI를 재시작하세요. CCD 촬영/검출/영상 전송은 변경하지 않았습니다.

네트워크 로컬 파일은 `server_host`, `server_port`, `motor_host`, `motor_port`만 받습니다. 실제 주소는 공개 기본 파일 대신 `connections.local.json`에 기록하세요.

## Flipper 역할 설정

먼저 메인 서버에 연결하고 flipper를 검색하면 현재 서버에 맞는 로컬 파일이 저장됩니다. 해당 파일의 `host`, `port`, `names`는 유지한 채 `routes`와 `auto_route`를 설정합니다. 다른 서버로 바뀌면 기존 경로는 자동 해제됩니다.

```json
{
  "auto_route": true,
  "routes": {
    "EA": {"mirror_a": 1, "mirror_b": 2},
    "EC": {"mirror_a": 2, "mirror_b": 1}
  }
}
```

위 코드는 파일 전체가 아닌 편집할 필드 예시입니다. `mirror_a/b`는 실제 서버 등록 이름으로 바꾸세요. 1/2는 기계 위치이며 왼쪽/오른쪽은 설치 방향에 따라 다릅니다. 경로에 적힌 장비가 연결되어 있어야 기존 포획 operation의 자동 경로 기능이 동작합니다. 설정 파일만 편집한다고 장비가 움직이지 않습니다.

## Scan 역할 설정

`scan_roles.json`의 배열 순서는 네 탭 순서입니다. `axes`는 X/Y/Z 순서이며 `pmt_index`는 현재 PMT 선택 목록의 0~3 인덱스입니다. 기본 매핑은 EA collection=p, EA excitation=s, EC collection=p, EC excitation=s를 유지합니다. PC별 변경은 전체 배열을 `scan_roles.local.json`에 복사해 편집하면 됩니다. 잘못된 이름/중복 축/범위를 벗어난 PMT 인덱스는 오류로 처리합니다.

## 기존 로컬 파일 이전

첫 실행 때 기존 config 루트의 개인 파일을 다음 위치로 이동합니다. 값은 그대로 보존하며 기존 파일과 새 파일이 둘 다 있고 내용이 다르면 덮어쓰지 않고 오류로 안내합니다.

- `local_hardware.json` → `devices/connections.local.json`
- `fpga_ports.local.json` → `devices/fpga/ports.local.json`
- `client_settings.json` → `ui/client_settings.local.json`
- `equipment.local.json` → `ui/equipment.local.json`
- `scan_*.local.json` → `ui/scan_*.local.json`
- `flip.local.json` → `operations/flipper_routes.local.json`
- `oven.local.json` → `operations/oven.local.json`

다른 PC에는 필요한 `*.local.json`을 새 상대경로 그대로 직접 복사합니다. 모두 기존 Git ignore 규칙으로 제외됩니다. 새 checkout에는 공개 기본값만 들어갑니다. 직접 선택한 외부 구성 파일의 경로는 계속 사용하므로 다른 PC에서 메인 Configuration의 불러오기로 다시 지정하세요.

## FPGA 출력 표시

AOMM, AOMB, CCD_EC, CCD_EA는 현재 HardwareDefinition에서 `jc_*` slow port입니다. 현 구현의 상태 읽기 응답은 fast/control port만 반환하므로 이 네 출력의 실제 ON/OFF를 읽을 수 없습니다. 연결 후 `읽기 미지원`으로 표시합니다. 성공한 출력 명령 이후 `ON *` / `OFF *`는 마지막 명령값이며 물리 상태를 검증했다는 뜻이 아닙니다. 통신 실패/미연결의 Unknown 표시와 구별합니다. 펌웨어나 출력 제어 명령은 변경하지 않았습니다.
