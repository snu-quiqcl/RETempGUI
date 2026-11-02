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

1. PSU OFF 및 잔류 전류 확인, 선택한 399 셔터 CLOSE
2. 활성화된 EA/EC flipper 경로 이동
3. 검출 ON 모드이면 기존 CCD 준비 과정 수행
4. EA/EC 171/174 릴레이 선택, CH1 전류 0 A 및 전압 제한 설정
5. PSU 출력 ON → 선택한 399 셔터 OPEN 및 route/readback 확인
6. 전류를 0.15 A씩 증가시키고 포획 또는 timeout/STOP 대기
7. 종료 시 **399 셔터 CLOSE → 전류 감소 → PSU OFF**

오븐 셔터와 399 셔터는 같은 장치이며 선택한 셔터 하나만 동작합니다. 다른 셔터는 조작하지 않습니다. 셔터 OPEN 실패 시 양의 전류로 ramp하지 않고 CLOSE/OFF 정리를 시도합니다. GPIO/readback 확인은 릴레이 서버 상태이며 물리적 날개 위치 센서 확인은 아닙니다.

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

CCD 아래 오븐 패널의 **399 shutter** 하나로 선택합니다. 기본은 shutter_1이며 shutter_2로 변경할 수 있습니다. Connect/Start 때 `labremote/config/operations/oven.local.json`에 저장됩니다.

```json
{
  "chamber": "EC",
  "psu_name": "oven_psu",
  "relay_name": "oven_relays",
  "photoionization_shutter": "shutter_1",
  "timeout_s": 600
}
```

기존 파일에 shutter와 photoionization_shutter가 모두 있으면 photoionization_shutter만 사용합니다. UI에서 다음 저장 시 별도 shutter 키는 제거됩니다. 옛 파일에 shutter만 있으면 그 값을 사용합니다.

Workflow는 `load_oven(..., photoionization_shutter="shutter_1")`로 선택합니다. 옛 `shutter=` 인자는 같은 장치의 별칭으로 지원하며 두 인자를 함께 지정하면 photoionization_shutter가 우선합니다. 둘 다 생략하면 로컬 설정을 사용합니다.

STOP·포획·timeout·오류 시 399 CLOSE가 정리의 첫 operation입니다. CLOSE 실패 시에도 PSU 감소/OFF를 시도하고 정리 실패를 표시합니다. 실행 중이 아닐 때 STOP도 선택한 셔터 CLOSE 후 PSU OFF를 요청합니다. Flipper는 종료 시 마지막 위치를 유지합니다.

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

auto_route=false면 자동 이동하지 않습니다. true인데 선택한 챔버 경로가 비어 있거나 장비가 연결되지 않으면 가열을 시작하지 않습니다. 399 셔터 번호는 oven.local.json에서 설정하며 챔버 이름으로 자동 추정하지 않습니다.

Workflow의 load_oven()도 chamber 생략 시 같은 로컬 설정을 읽습니다. 한 요청만 명시하려면 `devices.ccd().load_oven(171, chamber="EA").wait()`처럼 지정할 수 있습니다. UI 작업의 표시 챔버와 다른 명시적 workflow 요청은 operation의 route에 기록됩니다.
