# 검출과 오븐 동작 분리

| 검출 선택 | 오븐 상태 | 동작 |
| --- | --- | --- |
| ON | OFF | CCD 연속 촬영·검출, 이온 개수 표시. 오븐을 자동으로 켜지 않음 |
| OFF | OFF | 이온 분석/표시 중지. 이미 켠 Live 영상은 계속 표시 |
| ON | ON | 포획 조건 충족 또는 timeout / STOP 때 종료 정리 |
| OFF | ON | 포획 신호를 기다리지 않음. timeout / STOP 때 종료 정리 |

GUI 검출 버튼은 ON/OFF 토글입니다. 검출 설정을 바꾸려면 OFF 후 값을 바꾸고 ON 하세요. 오븐은 시작 시 검출 선택을 확정하고 실행 중에는 검출 설정을 잠급니다. OFF 모드에서는 CCD 연결이 필요 없으며 카메라 시작/정지/검출 명령도 보내지 않습니다. ON 모드는 실제 Thorcam 연결을 요구하며 기존의 threshold·화면 ROI·연속 프레임 조건을 유지합니다. 명시적인 workflow CCD wait는 GUI 검출 OFF와 별도로 동작합니다.

Timeout은 분·초 두 입력으로 설정하며 기본은 **10분 0초**입니다. 0분 0초는 허용하지 않습니다. 설정은 operations/oven.local.json의 timeout_s에 초 단위로 저장하지만 화면은 분·초로 표시합니다. 기존처럼 시작 준비와 ramp 시간도 제한 시간에 포함됩니다. timeout 시 즉시 종료 정리를 시작하며 전류 ramp down 및 OFF/CLOSE 확인에 걸리는 시간은 추가될 수 있습니다.

## 오븐 시작/종료 순서

1. PSU OFF 및 잔류 전류 확인
2. 오븐 셔터 및 399 셔터 CLOSE
3. 활성화된 EC flipper 경로 이동
4. 399 셔터 OPEN 확인 후, 검출 ON 모드에서 CCD 준비
5. EC 171/174 릴레이 선택 및 PSU 설정
6. 선택한 셔터 OPEN 및 readback 검증
7. PSU ON, 기존 0.15 A 단위 전류 ramp
8. 종료 조건 이후 **399 셔터 CLOSE를 먼저 시도·확인**, 그다음 전류 ramp down, PSU OFF, 오븐 셔터 CLOSE 확인

셔터 OPEN 단계가 실패하면 PSU ON으로 진행하지 않습니다. GPIO/readback은 릴레이 서버가 반환한 상태이며 별도 위치 센서가 없다면 셔터 날개의 물리적 이동까지 확인하는 것은 아닙니다.

셔터 상태는 오븐 패널과 Flipper 창에서 동일한 operation 상태를 표시합니다. OPEN은 초록, CLOSED는 빨강, 미연결/실패/미확인은 회색입니다. 오븐 작업 중에는 그 작업의 readback을 사용하고, 대기 상태의 조회는 기존 자동 조회 스케줄러를 사용합니다. 수동 셔터 창은 shutter_1과 shutter_2를 각각 상태 읽기 / OPEN / CLOSE할 수 있습니다. 오븐 실행 중에는 수동 조작을 잠급니다.

## 399 flipper 자동 경로

표시 별명 파일 ui/flipper_display.local.json은 이동 방향을 결정하지 않습니다.
실제 경로는 **operations/flipper_routes.local.json**에 설정합니다. 먼저 메인 서버에서 flipper 목록을 불러온 뒤, 생성된 파일의 host/port/names는 유지하고 아래 필드를 편집합니다.

```json
{
  "auto_route": true,
  "routes": {
    "EA": {},
    "EC": {"FLIP_399": 2}
  }
}
```

위 내용은 파일 일부의 예시입니다. FLIP_399를 실제 서버 등록 이름으로 바꾸고 Position 1/2 중 실제 EC 광로에 해당하는 위치를 입력하세요. 미리 해당 flipper를 연결해야 합니다. 매핑 장비가 없거나 이동에 실패하면 오븐 가열은 시작되지 않습니다. 포획 루틴은 oven.local.json의 chamber에 따라 EA 또는 EC 경로를 선택합니다. 이번 수정에서는 실제 경로 파일의 auto_route나 목표 위치를 임의로 변경하지 않았습니다.

## Workflow API

기존 load_oven()은 검출 ON 방식으로 유지됩니다. 타이머 방식은 다음처럼 명시합니다.

```python
devices.ccd().load_oven(171, detect_ions=False, timeout_s=10*60).wait()
```

검출 ON 방식은 `detect_ions=True`이며 기존 target/consecutive_frames/roi 인자를 계속 사용합니다. STOP/취소나 장비 오류에도 종료 정리를 수행하고, OFF/CLOSE 확인 실패는 정상 종료로 표시하지 않습니다.

## 399 셔터 선택과 종료 순서

CCD 아래 오븐 패널에 Oven shutter와 399 shutter를 별도로 표시합니다. 확인된 기본 구성은 오븐 shutter_2, 399 shutter_1입니다. 각 드롭다운에서 변경하면 다음 연결/Start 시 `labremote/config/operations/oven.local.json`에 저장됩니다.

```json
{
  "chamber": "EC",
  "psu_name": "oven_psu",
  "relay_name": "oven_relays",
  "shutter": "shutter_2",
  "photoionization_shutter": "shutter_1",
  "timeout_s": 600
}
```

시작 시 PSU OFF/잔류 전류와 안전한 경로 전환을 확인한 뒤 399 셔터를 엽니다. 399 OPEN은 CCD 준비 및 전류 설정/ramp보다 먼저 수행합니다. STOP·포획·timeout·오류에는 399 CLOSE가 종료 절차의 첫 operation입니다. 진행 중인 통신은 완료를 기다리지만, 전류 ramp down 완료를 기다렸다가 399를 닫는 방식은 사용하지 않습니다. 399 CLOSE 실패 시 오류를 남기고 전류 감소/PSU OFF/오븐 셔터 CLOSE를 계속 시도합니다. 두 역할에 같은 셔터를 지정하면 시작 OPEN과 종료 CLOSE를 중복 실행하지 않습니다.

실행 중인 오븐 task가 없는 상태의 STOP도 399 CLOSE 시도 완료 후 PSU OFF를 요청합니다. 별도 workflow에서는 `load_oven(..., photoionization_shutter="shutter_1")`로 지정할 수 있고, 생략하면 로컬 설정을 읽습니다.

## EA/EC 요청은 어디서 결정되나

`labremote/config/operations/oven.local.json`의 `"chamber": "EA"` 또는 `"chamber": "EC"`로 지정합니다. 생략하면 기존 호환을 위해 EC입니다. 다른 값은 가열 전에 오류로 처리합니다. 파일을 변경한 뒤 UI를 다시 실행하세요. CCD 아래 오븐 제목과 전류 설정 표시에 현재 챔버가 표시됩니다. UI는 표시된 챔버를 Start에 전달하고 실행 중에는 경로가 바뀌지 않습니다.

예를 들어 chamber=EA, isotope=171이면 릴레이는 EA_171, 전류 제한은 0.75 A/5 V, flipper는 routes.EA를 사용합니다. EC_171은 1.30 A/5 V, EC_174는 1.40 A/5 V, EA_174는 0.75 A/5 V입니다. 171/174는 동위원소이며 챔버와 독립적입니다.

flipper_routes.local.json의 기존 host/port/names를 유지하고 아래처럼 경로를 지정합니다. FLIP_399 및 위치는 예시이므로 실제 서버 이름과 광로에 맞게 설정해야 합니다.

```json
{
  "auto_route": true,
  "routes": {
    "EA": {"FLIP_399": 1},
    "EC": {"FLIP_399": 2}
  }
}
```

auto_route=false면 자동 이동하지 않습니다. true인데 선택한 챔버 경로가 비어 있거나 장비가 연결되지 않으면 가열을 시작하지 않습니다. 399 셔터와 Oven shutter 번호는 oven.local.json의 별도 설정이며 챔버 이름으로 자동 추정하지 않습니다.

Workflow의 load_oven()도 chamber 생략 시 같은 로컬 설정을 읽습니다. 한 요청만 명시하려면 `devices.ccd().load_oven(171, chamber="EA").wait()`처럼 지정할 수 있습니다. UI 작업의 표시 챔버와 다른 명시적 workflow 요청은 operation의 route에 기록됩니다.
