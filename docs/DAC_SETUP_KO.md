# DAC81416 API v2 설치·운용

## 구성

서버에는 `server_deploy_latest/DAC81416`만 배포합니다.
실제 구현은 `trap_dac/qcodes_driver.py`와 `trap_dac/ArtyS7.py` 두 파일입니다.
`__init__.py`와 `pyproject.toml`은 패키지 설치용입니다.
서버는 전극 이름, EA/EC 매핑, preset, sequence, 실험 파일을 처리하지 않습니다.
클라이언트는 기존 labremote 디렉터리 규칙을 따릅니다.
- devices/dac: UI, worker, 전압/preset 모델, sequence 파일 처리
- operation/dac: initialize, set_voltages, run_sequence, execute, timing
- config/dac.py: 설정 스키마·검증·경로 처리
- config/devices/dac: EA/EC 매핑·보정 JSON
루트 trap_dac 폴더는 제거했습니다. 서버 패키지의 trap_dac는 독립 배포용이며
클라이언트는 이를 import하지 않습니다.

InstrumentServer 환경에서 `python -m pip install /ABSOLUTE/DAC81416` 실행 후
`docs/examples/dac_server.example.yml`을 기존 instruments 설정에 합칩니다.
기존 init의 config_path, data_root, lease_seconds는 제거합니다.
QCoDeS와 pyserial이 필요합니다. GUI는 서버에 필요하지 않습니다.
internal_reference는 실제 보드 배선에 맞춰 서버 생성 인자로 지정합니다.

## 클라이언트 설정

기존 `labremote/config/devices/dac/EA.local.json`, `EC.local.json`은 클라이언트에 둡니다.
실제 보정값은 공개 example 파일로 대체하지 않습니다.
기본값은 장비 이름에 EA가 포함되면 EA.local.json, 그 외는 EC.local.json입니다.
다른 매핑은 DAC 화면의 Load client mapping에서 선택합니다. 경로는 UI 설정에 저장됩니다.
기존 UI 설정의 trap_dac/configs 경로는 새 config/devices/dac 위치로 해석됩니다.
새로 저장하는 기본 매핑 경로는 config 기준 상대 경로이므로 다른 PC로 옮겨도 유지됩니다.
매핑 파일 변경 후 다시 Load하고 Initialize해야 적용됩니다.
매핑 변경은 드라이버 출력을 바꾸지 않으며, 클라이언트의 출력 사용 상태를 해제합니다.
화면에 등록되지 않은 물리 채널도 초기화 시 보정된 목표 0 V로 활성화됩니다.
32채널 전체 사용을 전제로 하므로 해당 채널의 보정값도 유효해야 합니다.

Connect는 USB만 연결합니다. Initialize는 offset [2][16]과 초기 목표 전압 [2][16]을
전달하고 32채널을 초기화합니다. 초기화는 기존 출력을 일시 중단할 수 있습니다.
단순 클라이언트 재접속으로 자동 초기화하지 않습니다.
서버가 유지되고 보정 해시가 같으면 재접속 시 기존 configuration ID를 사용합니다.
각 출력 요청은 해당 ID를 보내며, 다른 초기화 뒤 오래된 ID의 요청은 거절됩니다.
동일 설정으로 다시 초기화해도 새 ID가 발행됩니다.
이 검사는 sequence 전체의 독점 사용을 제공하지 않습니다.

## 드라이버 API

```python
status = dac.connect()
status = dac.initialize(offsets, initial_voltages, use_ldac=True)
token = status['configuration_id']
dac.set_voltage(0, 3, 1.25, token)
dac.set_voltages([[0, 3, 1.25], [1, 7, 2.0]], token)
status = dac.get_status()
```

chip=0..1, channel=0..15, 두 행 배열은 칩 순서입니다.
목표 전압에서 해당 offset을 빼고 기존 16비트 변환식을 적용합니다.
목표 전압은 ±20 V, 보정된 명령 전압은 -20..19.9993896484375 V 범위입니다.
초과값을 자동으로 clamp하지 않습니다. +20 V는 offset에 따라 거절될 수 있습니다.
입력 전체를 검증한 뒤 쓰며, 중복 물리 채널과 NaN/무한대도 거절합니다.
set_voltages는 요청한 채널들만 기록하고 LDAC를 한 번 발생시킵니다.
use_ldac=False는 기록되는 채널부터 순차 반영됩니다.

UART 전송 오류가 발생하면 전송값/설정 ID를 무효화하고 추가 출력을 차단합니다.
Connect로 재연결한 뒤 명시적으로 Initialize해야 합니다. 자동 재시도하지 않습니다.
RPC timeout은 실행 실패와 같지 않습니다. 해당 호출은 서버에서 끝날 수 있습니다.
UI는 추가 요청을 멈추며, 재접속하여 서버 상태를 확인해야 합니다.
장비 상태 조회는 서버 메모리 조회입니다. 실제 출력 readback은 없습니다.
FPGA SPI 완료 응답 및 DAC readback은 현재 구현하지 않습니다.
명령 간격과 전송 큐 대기는 FPGA 완료 확인을 대신하지 않습니다.

## UI·Workflow

기존 initialize/apply/set_voltage/step/preset/sequence API를 유지합니다.
클라이언트가 전극 매핑을 물리 채널 요청으로 변환하고 보정은 드라이버가 계산합니다.
클라이언트의 값 검증은 사용자 오류 조기 검출용이며 DAC 코드는 전송하지 않습니다.
sequence는 worker thread에서 행별로 실행하며 hold는 응답 수신 후부터 시작합니다.
RPC와 UART 처리 시간이 추가되므로 정밀한 출력 주기는 보장하지 않습니다.
Stop·종료·UI heartbeat 중단은 다음 행을 막고 마지막 출력을 유지합니다.
진행 중인 원격 호출을 중간에 취소하거나 출력을 OFF하는 기능은 아닙니다.
단절된 클라이언트를 위해 서버가 sequence를 계속 실행하는 기능은 없습니다.
다른 클라이언트의 전압 변경은 행 사이에 들어올 수 있습니다.

일반 UI Disconnect는 그 클라이언트 연결만 닫습니다. 서버 USB와 출력은 유지합니다.
드라이버 disconnect()는 USB를 닫고 메모리 상태를 무효화하지만 출력 OFF를 보내지 않습니다.

실행 기록은 클라이언트 `labremote/data/dac/<EA|EC>/<날짜>/runs/<request-id>`에 저장됩니다.
request.json, client_result.json, sequence의 rows/*.json을 보관합니다.
서버에는 새 실행 기록을 만들지 않습니다.

## 검증 범위

가짜 UART/QCoDeS와 Qt offscreen 테스트로 초기화, 보정, 전체/부분 출력,
LDAC, 잘못된 입력, 전송 실패, 오래된 설정 ID, UI Quick/sequence 취소를 확인합니다.
InstrumentServer blueprint로 공개 메서드 노출과 JSON 직렬화를 확인합니다.
실제 FPGA/USB, 전압 계측, 배포된 원격 서버 연결은 별도 확인이 필요합니다.
