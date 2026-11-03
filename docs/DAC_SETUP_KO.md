# EA / EC 칩트랩 DAC 설치와 운용

USB는 Linux InstrumentServer PC에 연결합니다. UI PC는 USB를 열지 않습니다.
첨부 DAC 코드의 전극 매핑, 보정식, UART framing, 수동 timing과 sequence 파일
형식을 재사용했습니다. 화면은 Qt로 이식했고 Simulation은 노출하지 않습니다.
실장 칩의 출력 readback이나 FPGA ACK를 구현한 것은 아닙니다.

## 옮길 파일

서버에는 저장소 루트의 `trap_dac/` 폴더 전체를 복사합니다.
그 안의 `configs/EA.local.json`, `configs/EC.local.json`은 Git에서 제외되므로
직접 별도 전송해야 합니다. 이 두 파일에는 첨부 원본의 전극 매핑과 실제 보정값,
기본 전압이 보존되어 있습니다. 원본 COM 포트는 제거했습니다.
`EA.example.json`, `EC.example.json`은 동일한 전극 배치이지만 보정/전압을 0으로
비운 공개 예시이므로 실제 장비의 보정 파일 대신 사용하지 마세요.

UI PC에는 갱신된 저장소 전체를 pull/복사하면 됩니다. 특히 `trap_dac/`도 필요합니다.
UI는 해당 패키지의 순수 데이터 모델을 사용하고 qcodes_driver/serial은 열지 않습니다.
서버 등록 이름은 `dac_ea`, `dac_ec`를 기본으로 하며 다른 이름도 Configuration에서
family=dac로 등록할 수 있습니다. 장비의 실제 EA/EC 구분은 서버 매핑의 device로 결정됩니다.

## 서버 설치

기존 InstrumentServer 환경을 활성화하고, 실제 복사 위치에 맞춰 실행합니다.

```bash
conda activate entserver
python -m pip install -e /ABSOLUTE/trap_dac
python -c "from trap_dac.qcodes_driver import DAC81416; print('DAC driver import OK')"
python -m serial.tools.list_ports -v
ls -l /dev/serial/by-id/
```

가능하면 `/dev/ttyUSB0` 대신 `/dev/serial/by-id/...`를 설정합니다. EA/EC를 하나씩
분리/연결해 어느 USB가 어느 DAC인지 확인하세요. 두 이름에 같은 포트를 지정하지 않습니다.
기존 DAC 프로그램은 닫아야 합니다. Linux 계정에 해당 serial 장치 접근 권한이 필요합니다.
권한이 없다면 장치의 그룹을 확인하고 관리자에게 그 그룹의 접근 권한을 요청합니다.

`docs/examples/dac_server.example.yml`의 두 장비 항목을 기존 serverConfig.yml의
**하나의 instruments 아래** 합칩니다. `init`의 경로/포트를 실제 값으로 수정합니다.
QCoDeS와 InstrumentServer는 기존 서버 환경에 설치된 것을 사용합니다.
YAML의 `initialize: true`는 드라이버 객체 생성만 의미하며 USB open/출력 초기화가 아닙니다.

`internal_reference: false`는 기존 코드가 내부 기준전압을 활성화하지 않았던 동작을
따릅니다. 보드가 외부 기준전압을 사용하는지 확인하세요. 내부 reference 배선으로
설계된 보드라면 서버 담당자가 true로 설정해야 합니다. 자동 추측하지 않습니다.
`data_root`는 **서버 파일시스템의** 절대 경로이며 EA/EC 하위 디렉토리는 자동 생성합니다.
서버에서 GUI를 설치하지 않아도 이 경로는 생성해 쓸 수 있습니다.

## UI 연결과 사용

1. InstrumentServer 재시작 후 메인 Configuration에서 dac_ea/dac_ec를 추가하고
   family `dac`, group `DAC`, 사용 체크를 설정합니다.
2. 메인 DAC 연결 또는 장비 메뉴 → DAC → 해당 탭 Connect를 누릅니다.
   연결은 USB만 열며 전압 명령은 전송하지 않습니다.
3. 연결 시 서버의 전극 매핑과 보정 설정을 가져옵니다. 연결 전 화면은 공개 예시입니다.
4. 초기 출력 `0 V` 또는 `Current draft`를 선택하고 Initialize DAC를 누릅니다.
   프리셋으로 초기화하려면 먼저 Open/Load로 입력값을 불러옵니다.
5. Apply/Enter/Quick ±는 실제 출력합니다. 숫자 입력과 프리셋 로드는 출력하지 않습니다.
   Quick은 기존처럼 현재 draft 전체를 기준으로 전송합니다. 입력 중인 다른 값도 함께 적용됩니다.
6. Use LDAC 선택은 다음 Apply/Sequence에 적용됩니다. 체크 변경 자체는 출력하지 않습니다.
7. Sequence 탭에서 행/hold를 편집한 뒤 Start. Stop은 현재 전송 행과 LDAC를 마친 뒤
   다음 행을 실행하지 않습니다. Hold 중이면 Hold를 즉시 끊고 마지막 전압을 유지합니다.

EA/EC manual과 sequence에서 LDAC 선택을 공유합니다. Manual Timing은 command gap,
pre-LDAC, cooldown을 설정합니다. Sequence는 첫 행 전체, 다음 행부터 변경된 DAC 코드만
전송하며 SPI 설정 재사용과 pre-LDAC 대기를 설정할 수 있습니다.
시간은 PC/서버 기준으로, Hold 외에 전송과 파일 기록 시간이 추가됩니다.
두 별도 DAC FPGA의 출력 시점이 동시에 맞춰진다는 보장은 없습니다.

## 초기화와 장애 동작

값/매핑 검증 → 두 칩 모든 채널 power-down → SPI/기준전압/±20V/toggle/sync 설정 →
모든 채널 초기 코드 기록 → 전송/안정화 대기 → LDAC 설정 → 사용 채널만 출력 활성화.
사용하지 않는 채널은 midscale을 기록하되 power-down을 유지합니다.
일반 초기화는 FPGA RESET을 보내지 않습니다. SPICONFIG reserved bit7과 GENCONFIG
reserved bits를 유지합니다. 0V는 보정식을 적용하며 무조건 데이터 0을 쓰지 않습니다.
초기화는 이미 가해진 전압을 잠시 끊으므로 전압 유지 상태의 일반 변경에는 Apply를 사용합니다.
정상 동작 여부와 초기화 전환 파형은 설치 후 계측기로 확인해야 합니다.

실행은 비동기 서버 job이며 InstrumentServer 요청 처리 스레드에서 기다리지 않습니다.
서버는 같은 DAC에 대한 겹치는 요청을 거절합니다. 요청 ID를 이용해 응답 손실로 인한
동일 실행의 재전송을 방지합니다. UI는 timeout 후 출력 명령을 자동 재시도하지 않습니다.

실행 중 UI는 약 1초마다 heartbeat를 보내며 기본 5초간 수신하지 못하면 서버가 중단합니다.
UI 메인 이벤트 루프가 2.5초 이상 멈춰도 heartbeat를 갱신하지 않습니다.
heartbeat/상태 조회는 DAC readback이 아니라 서버 메모리 조회입니다.
다른 UI 세션은 원래 실행자의 lease를 연장할 수 없습니다. 단절 시 current row 완료 후
중단하고 자동 재개하지 않습니다. 서버/USB 자체가 고장나면 행 완료나 출력값을 보장할 수 없습니다.
공유 InstrumentServer가 다른 장비의 긴 동기 요청으로 막히면 heartbeat도 지연되어
DAC가 중단될 수 있습니다. 이 경우 lease를 무작정 늘리기보다 DAC를 별도 InstrumentServer
프로세스/포트로 분리하고 해당 UI 연결 endpoint를 사용하는 운용을 검토하세요.

UI 종료/Stop과 네트워크 단절은 출력 OFF가 아닙니다. 마지막 전압 유지가 명시된 정책입니다.
재접속 시 서버가 살아 있으면 마지막 전송 상태를 조회합니다. 서버 재시작 후에는 캐시를
실제 출력으로 복원하지 않으며 초기화가 필요합니다.

## 매핑 수정

서버의 EA.local.json/EC.local.json에서 electrode id → chip(0/1), channel(0..15),
display position과 calibration_offsets를 수정합니다. UI Mapping 버튼은 내용을 보여줍니다.
Reload server mapping은 검증 후 USB를 닫고 서버 파일을 다시 읽습니다. 이후 Connect와
Initialize를 다시 실행합니다. 배선이 바뀌면 이전 sequence를 비우고 프리셋 배선 일치 검사를 합니다.
UI가 보낸 보정값으로 서버 보정값을 덮어쓰지 않습니다. 설정 fingerprint가 다르면 출력 전에 거절합니다.

## 저장과 API

UI: `labremote/data/dac/EA|EC/presets`, `sequences`, `runs/<request-id>`.
서버: `<data_root>/EA|EC/runs/<request-id>`에 요청·전체 설정·결과를 저장합니다.
sequence는 그 실행 폴더 안에 기존 형식의 전체 계획/최종 보고서와 행별 전압 JSON을 보존합니다.
UI progress는 최신 진행 스냅샷이며 완전한 행별 기록은 서버에 있습니다.
두 PC의 파일은 자동 동기화되지 않습니다. 서버 데이터를 따로 복사해 보관하세요.
모든 실행 데이터, `.local.json` 설정은 Git에서 제외됩니다.

UI 입력은 기존 input_state.local.json으로, timing·폴더·유효한 sequence 편집 내용은
`config/ui/dac_<instrument>.local.json`으로 정상 종료 시 저장합니다.

공통 API: `devices.dac(name)` → `initialize`, `apply`, `set_voltage`, `step`,
`load_preset`, `save_preset`, `create_sequence`, `load_sequence`, `save_sequence`,
`run_sequence`, `reload_configuration`, `refresh`, `cancel`.
출력 API는 ExecutionHandle을 반환합니다. Workflow에서는 `.wait()`를 사용하고
실패/중단은 예외로 전달되어 기존 queue의 실패 정책을 따릅니다.
`docs/examples/dac_workflow.py`를 기존 Workflow 탭에서 열 수 있습니다.
서버 RPC는 `describe_dac`, `start_dac_job`, `dac_job_status`, `dac_heartbeat`,
`stop_dac_job`이며 일반 사용자는 위 공통 API를 사용하면 됩니다.

## 검증 범위

가짜 UART로 초기화 명령 순서, 전체 초기 코드 선기록, 보정, 미사용 채널 power-down,
취소, heartbeat 만료, 소유권, 중복 요청, 파일 호환과 UI/API 실행 경로를 검증합니다.
실제 DAC 보드/서버에 연결하거나 전압을 출력한 검증은 수행하지 않았습니다.
