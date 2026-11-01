# MFF101 5대 + EC 셔터

`others → flip` 탭에서 서버 목록을 불러오고 실제 서버 장비 이름을 선택해 연결합니다.
예를 들어 `EA_PMT`, `FLIP_399`를 그대로 사용하며 `flip_1`~`flip_5`로 이름을 바꿀 필요가 없습니다.
다섯 개의 창을 열지 않고 하나의 선택창과 상태표를 사용합니다.
각 장비는 독립적인 operation 큐를 사용하고 GUI 스레드는 통신 응답을 기다리지 않습니다.

## 서버 PC / UI PC 배포

Linux 서버에는 별도 제공한 `flipserver` 폴더 전체를 복사합니다.
핵심 파일은 `MFF101/driver.py`, `flippers.example.yaml`, `start_flip_server.sh`이며
설치·USB 검색은 서버 폴더 README.md를 따릅니다. 기본 포트는 5556입니다.
기존 InstrumentServer에 YAML 항목을 병합하면 해당 포트를 그대로 사용할 수 있습니다.

UI는 최신 RETempGUI 소스를 적용합니다. 이번 변경 경로:

- `labremote/devices/flip/` 전체
- `labremote/operation/flip/` 전체
- `labremote/config/flip/` 전체
- `labremote/config/flip.example.json`
- `labremote/runtime/discovery.py`
- `labremote/ui/main_window.py`
- `labremote/devices/oven/runner.py`
- `labremote/devices/oven/panel.py`

기존 `oven_psu` 드라이버와 전류 ramp 작업 코드는 이번에 변경하지 않습니다.
Flipper는 메인 창 상단 InstrumentServer의 Host/Port를 사용합니다. Flip 탭에는 별도 서버 입력이 없습니다. 경로 설정은 Git에서 제외된
`labremote/config/flip.local.json`에 저장됩니다. 실제 주소·USB serial은 공개 예제에 넣지 않습니다.

## 수동 제어

1. 메인 창 상단 InstrumentServer에 flipper가 등록된 QCoDeS 서버 Host/Port를 입력합니다.
2. 상단 `Rescan server devices` 또는 flip 탭의 `서버 flipper 목록 불러오기`를 누릅니다. 서버의 장비 목록과 Blueprint 드라이버 정보에서 MFF101/MFF002를 구분합니다. 이 단계는 장비를 움직이지 않습니다.
3. `Flipper 전체 연결` 또는 각 장비의 연결 버튼을 누릅니다.
4. 원하는 장비에 해당하는 위치 읽기 또는 Position 1/2 버튼을 누릅니다.
5. Position 1/2의 실제 광로 의미는 현장에서 확인합니다. 자동으로 IN/OUT이라고 가정하지 않습니다.
6. EC 셔터 연결은 메인 창의 서버 주소와 Configuration의 oven_relay 장비 이름을 사용합니다.
   실제 제어 파라미터는 `oven_relays.shutter_2`입니다. 별도의 셔터 USB 드라이버는 만들지 않습니다.

오븐과 셔터는 같은 worker를 공유합니다. 오븐 로딩/자동 경로 이동 중 수동 제어를 막으며,
flipper/셔터 명령이 남아 있으면 오븐 로딩 시작을 거부합니다. 셔터의 읽기는 릴레이 GPIO
상태이며 물리적 개폐 센서의 보증은 아닙니다. 외부의 다른 클라이언트까지 잠그지는 않습니다.

## EA / EC 경로 설정

`flip.example.json`은 자동 전환 OFF와 빈 EA/EC 매핑을 제공합니다.
EA/EC의 각 flip 위치를 확인하기 전에는 자동으로 움직이지 않습니다.
EA/EC 경로 설정·수동 적용 버튼은 현재 UI에서 제거했습니다. 기존 자동 경로는 유지됩니다.
경로를 수정할 때는 장비 작업을 멈추고 `flip.local.json`의 routes와 auto_route를 편집합니다. 빈 EC 경로는 자동 적용할 수 없습니다.
서버 목록에서 사라진 장비는 경로에서 제거하거나 서버 이름을 확인한 뒤 다시 조회해야 합니다.

경로는 `flip.local.json`의 `routes.EA` 또는 `routes.EC`에 저장되며, 해당 경로에 필요한
장비 이름을 key, 목표 Position 1 또는 2를 value로 넣습니다. 지정하지 않은 장비는 움직이지 않습니다.
필요한 모든 장비가 매핑에 포함되었는지는 실제 광로를 기준으로 확인해야 합니다.
메인 서버 Host/Port를 변경하여 조회하면 기존 경로와 저장 목록은 초기화되고 자동 적용은 OFF가 됩니다. 새 서버에 맞게 다시 설정하세요.
설정 파일은 Git에서 제외되므로 다른 UI PC로 옮길 때 `labremote/config/flip.local.json`을 직접 복사하세요. 이번 서버 이름 조회 기능에는 Linux 서버 코드 교체가 필요하지 않습니다.

기존 경로 API는 셔터를 닫고 매핑된 장비를 순서대로 이동합니다. 수동 경로 적용 버튼은 표시하지 않습니다.
완료 후에도 셔터는 닫힌 상태입니다. 미설정 매핑은 이동 없이 오류를 표시합니다.

`auto_route: true`를 명시한 경우 현재 EC 오븐 workflow는 출력 OFF·셔터 닫기 이후,
CCD acquisition 시작과 오븐 가열 전에 EC 매핑을 적용합니다. 실패하면 가열하지 않고
기존 OFF/셔터 닫기 정리 경로로 갑니다. 기본 false이면 기존 오븐 동작을 유지합니다.

EA 매핑 적용 기능은 준비했지만 기존 오븐 로딩 자체는 여전히 EC 전용입니다.
EA 오븐 로딩, 포획 후 flipper 복귀, 각 광로의 정확한 이동 순서는 사용자가
매핑/시점을 지정한 뒤 연결해야 합니다. 지금은 그 동작을 추정해서 실행하지 않습니다.

## 검증 범위

모의 QCoDeS backend, 5개 remote worker, EC 오븐 workflow, Qt 버튼 제어로 검증했습니다.
실제 Linux MFF101/USB 장비 검증은 미수행입니다. 연결 중 이동 없음, 선택 장비만 이동,
셔터 OPEN/CLOSED, 자동 매핑 실패 시 가열 금지, 기존 오븐 ramp/CCD cleanup을 확인합니다.

드라이버 근거: [pylablib MFF](https://pylablib.readthedocs.io/en/latest/.apidoc/pylablib.devices.Thorlabs.html),
[Thorlabs APT](https://www.thorlabs.com/Software/Motion%20Control/APT_Communications_Protocol_v40.pdf).

FPGA 출력·광자수·Scan 화면은 `others` 안이 아니라 최상위 `FPGA` 탭에 있습니다.
목록 조회는 12초(클라이언트 생성자에는 12000 ms) timeout을 사용합니다.
