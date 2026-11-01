# RETempUI 장비 상세 가이드

기존 v6 장비 기능에 대한 설명입니다. 현재 배포본의 설치와 CCD 기능은 [README](../README.MD)와 [CCD 가이드](CCD_GUIDE_KO.md)를 참고하세요.

# LabRemote Client v6 — RF / oscillo / mira / others / workflow

v5를 보존하고 별도로 만든 클라이언트입니다. Windfreak·SG384·AnaPico APSYN420·DDS AD9912/VVA·Rigol DS1052E/MSO7054·THERMOTEK T257P·Keithley 2231A를 공통 실행 구조로 제어합니다. 상위 탭은 `RF`, `oscillo`, `mira`, `others`, `workflow`입니다. 장비 서버나 실제 출력 설정은 이 구현 작업에서 변경하지 않았습니다.

## 추가 장비

| 탭 | 장비 이름 | 기능 |
|---|---|---|
| oscillo → MSO7054 | mso7054 | CH1–4 파형, 수평/수직/트리거 설정, RUN/STOP, Vavg/Vrms/Vpp/Vmax/Vmin |
| mira → THERMOTEK | t257p | 목표 온도, Pump RUN/STOP, 온도·유량·watchdog 조회와 그래프, 수동 raw 진단 조회 |
| others → Keithley | keithley_ps | CH1–3 전압/전류 설정, 출력 ON/OFF, OVP 설정, 전압/전류/파워 측정 |

각 장비는 독립 worker 스레드와 FIFO 큐를 가집니다. DS1052E/MSO7054 파형과 THERMOTEK 반복 측정은 장비별 반복 스레드가 같은 API를 호출하고 완료를 기다립니다. 동시 시작은 거부하며 취소·오류·timeout에 반복을 멈춥니다. 연결 해제 시 재시작을 막고 수동 Connect 후 해제합니다. 종료 시 worker와 반복 스레드를 모두 정리합니다. 실제 서버가 통신을 직렬 처리하면 물리적인 요청 처리는 여전히 순차적일 수 있습니다.

THERMOTEK의 `Start monitoring`은 기본적으로 한 회 조회 완료 후 6초를 기다립니다. `Stop monitoring`은 측정만 멈춥니다. `Pump STOP`은 별도의 장비 명령입니다. Connect만으로 펌프를 켜거나 반복 조회를 시작하지 않습니다. 온도는 5–40 °C이고 장비 알람이 있으면 목표 온도 변경과 RUN은 assign에서 차단합니다. RUN/STOP의 readback은 별도 `pump_running` get이며, 열적 안정화까지 기다리는 기능은 아닙니다. raw 진단은 자동 반복에 섞지 않으며 값의 단위는 원래 장비 프로토콜 단위입니다.

Keithley 제한은 기존 설정을 유지합니다: CH1 5 V/1 A, CH2·CH3 5 V/3 A. 설정 파일은 모두 `labremote/config/<장비>/`에 있습니다. API와 UI 모두 같은 assign 제한을 적용하며, 출력 ON 시 현재 설정도 범위 내인지 확인합니다. 실제 전압/전류 측정과 설정값 readback은 구분됩니다.

MSO7054는 BYTE/NORM 화면 파형을 읽습니다. 압축 해제·크기 제한·preamble 검증은 acquire에서 수행하고 operation은 보정식으로 시간/전압 배열을 만듭니다. 꺼진 채널은 건너뛰고, 선택 채널 중 통신/디코딩 오류가 발생하면 전체 operation과 반복을 중단합니다.

```python
def main(devices):
    scope = devices.mso7054('mso7054')
    traces = scope.read_waveforms(('CH1', 'CH4')).wait()
    chiller = devices.thermotek('t257p')
    readings = chiller.read_telemetry().wait()
    supply = devices.keithley('keithley_ps', channel=1)
    voltage = supply.acquire('ch1.voltage').wait()
```

반복은 `scope.start_waveform(..., interval_s=1)` 또는 `chiller.start_monitoring(interval_s=6)`입니다. 반환된 핸들의 `cancel()`로 취소하고 `wait()`로 종료를 기다립니다. workflow에서 시작한 반복은 해당 workflow의 취소 그룹에 속하므로 workflow 전체 취소와 오류 중단 정책을 따릅니다. 읽기 예제는 `labremote/workflow/read_mso7054.py`, `read_thermotek.py`, `read_keithley.py`에 있습니다. 서버 파일 호환성은 `server_deploy_latest/README.md`를 참고하세요.

## SG384 파워 입력 단위

BNC와 N 출력별 Power 행의 숫자 입력창 뒤에서 dBm/Vpp를 선택합니다. Step 뒤에도 단위 선택이 있으며 파워 설정값과 Step 단위는 함께 전환됩니다. 단위별 Step 크기는 따로 기억합니다. 단위 변경은 입력값과 표시값만 환산하며 Apply를 눌러야 장비에 전송합니다. 입력창은 config의 파워 상한과 장비 범위로 제한되며, 단위를 바꿔도 제한이 유지됩니다. Vpp는 50 Ω 부하에 걸리는 정현파의 peak-to-peak 전압입니다. 내부 파라미터와 readback은 dBm을 유지하고 기존 Vpp 간격 ramp를 사용합니다.

RF 주파수의 설정값과 Step 단위는 각각 선택할 수 있습니다. SG384는 MHz/kHz/Hz, Windfreak와 AnaPico는 GHz/MHz/kHz/Hz를 지원합니다. 예를 들어 설정값은 MHz, Step은 kHz로 사용할 수 있으며 단위를 바꿔도 Hz 기준 설정값·증가량은 유지됩니다. 숫자 입력창 안에는 단위를 넣지 않습니다. Windfreak 파워는 입력창 뒤에 고정 dBm을 표시합니다. 이 Step은 UI 화살표의 증가량이며 operation의 파워 ramp 설정은 변경하지 않습니다.

```python
def main(devices):
    rf = devices.sg384('sg384_EA', port='N')
    rf.set_power(0.1, unit='Vpp').wait()
    measured_dbm = rf.acquire('n_power_dbm').wait()
```

기존 `set_power(-20)` 호출은 계속 dBm입니다. `labremote/config/devices/sg384/device_config.yml`의 `max_power_vpp`는 dBm으로 변환해 각 ramp 단계의 assign에서 검사합니다. `max_power_dbm: null`이어도 Vpp 제한은 적용되며, 두 제한이 있으면 더 낮은 값을 사용합니다. 현재 EA의 0.16 Vpp는 약 −11.94 dBm, EC의 0.19 Vpp는 약 −10.45 dBm입니다. 제한 초과 단계에서 중단되며 그 전에 변경된 값은 유지됩니다.

## DS1052E

`oscillo → DS1052E`에 `ds1052e_EA`, `ds1052e_EC`를 등록합니다. Connect는 장비 확인과 설정 조회만 수행하며 Run/Stop이나 설정 변경은 하지 않습니다. 수평·채널별 수직·트리거 설정, 채널 표시, Run/Stop, 600샘플 화면 파형 조회를 지원합니다. 파형은 deep memory가 아닌 LCD 화면 데이터입니다.

UI와 workflow 모두 같은 API/worker 큐를 사용하며 파라미터 검증은 acquire/assign에서 수행합니다. Run/Stop과 waveform mode는 서버의 쓰기 전용 파라미터여서 readback을 수행하지 않습니다. 일반 설정 모니터링은 60초 간격입니다. `Start live waveform`은 별도로 사용자가 켜는 연속 파형 조회이며, 조회 오류 시 중단하고 자동 재시도하지 않습니다.

반복 조회는 UI 타이머 대신 `runtime/waveform_runner.py`의 장비별 `WaveformRunner`가 관리합니다. EA와 EC는 독립된 반복 스레드·취소 그룹·worker 큐를 사용합니다. 매회 공통 `read_waveforms()` 핸들의 완료를 기다린 뒤 지정 간격을 기다리므로 조회 요청이 누적되지 않습니다. 장비 점유는 매 operation 단위이며 다른 요청도 FIFO 순서대로 실행됩니다.

`scope.start_waveform(channels=('CH1','CH2'), interval_s=1.0)`은 반복 전체의 실행 핸들을 즉시 반환합니다. `capture.cancel()` 또는 `scope.stop_waveform()`으로 취소합니다. `capture.wait()`는 반복이 끝날 때까지 기다리며 취소·실패를 예외로 전달합니다. Stop waveform은 Scope STOP 명령을 보내지 않습니다. 시작 시 선택한 채널과 간격을 고정하고, 실행·중단 중 중복 시작은 거부합니다.

일반 workflow에서 시작하면 상위 workflow의 취소 그룹과 연결됩니다. 상위 취소는 반복을 중단하고 반복 오류도 상위 workflow를 중단합니다. 반대로 반복 핸들을 취소해도 상위 workflow 전체가 취소됩니다. 무한 반복을 시작한 workflow는 명시적 취소나 오류가 있을 때까지 종료되지 않습니다.

취소 시 간격 대기는 즉시 종료하지만 진행 중 통신은 응답 또는 timeout까지 기다립니다. 오류와 취소가 겹치면 실제 통신 오류를 보존합니다. Disconnect와 앱 종료는 반복을 취소하고 진행 중 요청 및 반복 스레드가 정리될 때까지 기다립니다. 중단한 실행의 지연 파형 결과는 UI에 다시 표시하지 않습니다.

```python
def main(devices):
    scope = devices.ds1052e('ds1052e_EA')
    time_scale = scope.acquire('time_scale').wait()
    result = scope.read_waveforms(('CH1', 'CH2')).wait()
    if 'CH1' in result['traces']:
        times, volts = result['traces']['CH1']
```

설정은 `labremote/config/ds1052e/`에 모았습니다. 서버에는 기존 `RigolDS1052E` 드라이버와 해당 장비 이름이 등록되어 있어야 합니다. DS1052E workflow 예제는 `labremote/workflow/read_ds1052e.py`입니다.

Trigger source 응답의 `CH1/CH2`는 acquire에서 `CHAN1/CHAN2`로 정규화하며 assign readback도 같은 값을 비교합니다. 시간·수직 스케일은 acquire에서 유한한 양수인지 검사합니다. 파형 압축 해제·600샘플 검증은 공통 acquire의 파라미터 타입 처리에 포함되어 별도 `waveform_codec.py`가 없습니다. 채널 선택은 각 operation에서 처리합니다.

DS1052E 응답 형식은 `parameter_registry.yml`에서 지정합니다. 공통 acquire가 아래 규칙을 적용하며 assign 요청값 자체를 느슨하게 변환하지 않습니다.

| 파라미터 | acquire 응답 처리 |
| --- | --- |
| CH1/CH2 display | 숫자·불리언 1/0, 문자열 `1/0`, `ON/OFF` → `ON/OFF` |
| Trigger source | `CH1/CHAN1/CHANNEL1`, CH2 대응 표기 → `CHAN1/CHAN2` |
| Trigger slope | `POSITIVE/POS`, `NEGATIVE/NEG` → `POS/NEG` |
| Trigger sweep | `NORMAL/NORM`, `SINGLE/SING`, `AUTO` → `NORM/SING/AUTO` |
| Trigger mode/status | 문자열의 앞뒤 공백·개행 제거 및 대문자화 |
| 시간·수직 scale/offset, trigger level | 숫자 및 지수 표기 숫자 문자열 허용; 유한성·양수 스케일 검사 유지 |
| Frequency/Vpp | 숫자·숫자 문자열 처리; 측정 불가 sentinel은 미확인 값으로 유지 |
| Version / device info / waveform | 정수 응답, JSON 장비 식별, 압축 파형 검증 유지 |
| waveform mode / Run·Stop | 쓰기 전용이므로 get/readback을 추가하지 않음 |

표기 정규화 후에도 알 수 없는 응답과 readback 불일치는 오류입니다. 숫자나 문자열 변환 규칙은 해당 DS1052E config에만 적용하며 다른 장비의 검증 정책은 유지합니다.

파형 결과에는 조회 당시 시간축 설정도 포함됩니다. UI는 현재 라이브러리의 설정, 반복 실행 ID, 핸들의 완료 순서를 확인합니다. 다음 조회가 진행 중이어도 마지막 완료 파형은 표시하며, 더 최신 완료 결과를 표시한 뒤에는 이전 결과로 되돌아가지 않습니다. 서버의 트리거 레벨 설정에도 CH1/CHAN1 호환 수정이 필요하므로 `server_deploy_latest/README.md`의 배포 안내를 참고하세요. 실행 중인 서버에는 자동 배포하지 않습니다.

## 실행

`start_lab_remote_gui.bat`를 실행합니다. 기본 환경은 기존과 같은 `C:\Anaconda`, Conda `uniqcon`입니다. 서버 Host/Port를 확인하고 `Rescan server devices` 또는 장비 이름과 `Add device`로 탭을 추가한 뒤 Connect를 누릅니다. 앱 시작 시 자동 연결하거나 RF를 켜지 않습니다. DDS의 명시적 Connect 시 직렬 초기화 동작은 아래 설명을 참고하세요.

## 구조

- `labremote/api/devices.py`: UI/workflow 공통 API. 즉시 ExecutionHandle 반환.
- `labremote/runtime/jobs.py`: 핸들, 완료 대기, workflow 전체 취소.
- `labremote/runtime/runner.py`: 실행 상태, operation 단위 점유와 결과·알림 처리.
- `labremote/runtime/device_worker.py`: 장비별 worker가 공유하는 FIFO 큐와 통신 수명 관리.
- `labremote/operation/windfreak/`: Windfreak 작업 정의.
- `labremote/runtime/parameters.py`: acquire/assign 검증, readback, 공유 관측값.
- `labremote/config/operations/windfreak/parameter_registry.yml`: 파라미터 타입·범위·readback 정책.
- `labremote/config/devices/windfreak/device_config.yml`: 장비별 출력 한계·reference 기본값. Ramp는 `labremote/config/operations/windfreak/operation_config.yml`.

Config는 operation 시작 때 읽어 고정합니다. 값 검증은 acquire/assign에서 수행합니다. Operation은 사전 값 검증을 하지 않으며, 오류 전에 성공한 변경은 유지합니다. Ramp는 각 단계의 값을 assign에서 검증하고 씁니다. 범위를 벗어나는 단계에서 중단하며 이전 단계에서 성공한 변경은 유지합니다.

## Workflow

Workflow 탭에서 Python 파일만 선택합니다. 파일의 `main(devices)`가 고정 실행 진입점이며 함수 선택은 없습니다. 탭의 편집기에서 코드를 수정하고 저장(Ctrl+S)하거나 다른 이름으로 저장할 수 있습니다. **저장 후 실행**은 현재 편집 내용을 저장하고 고정한 뒤 별도 QThread에서 실행합니다. UI 스레드에서는 wait()를 호출하지 않습니다.

```python
def main(devices):
    rf = devices.windfreak('synthhd_760', channel='A')
    rf.acquire('channel_A.frequency_hz').wait()
    rf.acquire('channel_A.power_dbm').wait()
```

wait()는 완료까지 기다리고 실패·취소를 예외로 전달합니다. acquire는 해당 요청이 읽은 값을 반환하고, 내부 라이브러리 갱신과 장비 화면 반영도 유지합니다. Workflow 화면은 파라미터 표 없이 성공·실패·취소 상태만 표시합니다. Workflow 전체가 장비를 점유하지 않으므로 단계 사이에 다른 UI operation이 실행될 수 있습니다.

`read_windfreak.py`는 읽기 예제, `set_windfreak.py`는 주파수와 파워 쓰기 예제입니다. 쓰기 예제의 장비 이름·채널·목표값을 편집한 뒤 실행하세요. `set_frequency()`와 `set_power()` operation이 내부 assign/readback을 수행합니다. 주파수·위상·파워 변경은 RF ON/OFF와 관계없이 별도 확인창 없이 실행합니다.

실행 중에는 파일 선택과 편집을 잠그며, 외부에서 파일이 변경돼도 진행 중인 실행에는 영향을 주지 않습니다. 파일 전환·새로고침·앱 종료 시 미저장 편집 내용을 확인합니다. 저장 실패 시 파일을 교체하거나 실행하지 않습니다.

## 오류·취소·통신

- 일반 오류/readback 불일치: 해당 operation 중단, 알림, 다음 독립 큐 요청 처리.
- Workflow 오류: 해당 workflow의 이후 단계 중단.
- Workflow 취소: 해당 그룹의 대기·실행 요청에 적용. 진행 중 assign은 readback까지 끝내며 자동 OFF/rollback하지 않음.
- Timeout: 실패 요청 재시도 없음. 소켓 재생성 후 다음 독립 요청 처리.
- 소켓 재생성 후에도 응답 없음: 연결 오류로 전환. 이후 요청은 통신 없이 실패 처리.
- 연결 오류 해제: 사용자가 Connect를 요청하고 실제 서버·장비 조회에 성공해야 함.
- Timeout은 서버의 기존 명령을 취소하지 않음. 관련 값이 불명확하면 명시적으로 acquire.

모니터링은 60초마다 마지막 성공 get 시각을 확인합니다. 같은 파라미터의 대기/실행 모니터 요청은 중복 생성하지 않습니다. 이미 대기한 요청은 유지합니다. 실패 시 성공 시각은 갱신하지 않고 다음 주기에 다시 판단합니다. 연결 오류 상태에서는 모니터 통신을 생성하지 않습니다.

## 검증

프로젝트 디렉터리에서 InstrumentServer checkout을 PYTHONPATH에 둔 상태로 실행합니다.

```powershell
& 'C:/Anaconda/envs/uniqcon/python.exe' -m unittest discover -s tests -v
& 'C:/Anaconda/envs/uniqcon/python.exe' -m tests.gui_smoke
```

테스트는 모의 장비와 모의 소켓을 사용합니다. 실제 장비의 readback 정밀도와 서버 응답 시간은 실기 확인이 필요합니다. `v6_preview.png`, `v6_workflow_preview.png`는 장비에 연결하지 않고 렌더링한 화면입니다.

## 설정 위치

- `labremote/config/ui/client_settings.local.json`: 서버 주소, 화면 설정, 장비 목록.
- `labremote/config/devices/windfreak/device_config.yml`: Windfreak 기본값과 장비 이름별 override.
- `labremote/config/operations/windfreak/parameter_registry.yml`: Windfreak 전체 파라미터 검증/readback 정책.

새 장비는 `labremote/config/<장비 종류>/`에 설정 파일을 추가합니다. 설정 로더 코드와 모든 설정 데이터는 `labremote/config/`에 함께 두며, 데이터 파일도 이 경로에서만 읽고 저장합니다. Operation 시작 시 각 장비 설정과 파라미터 정책을 함께 고정합니다.

`api.monitor()`도 공통 ExecutionHandle을 반환합니다. 선택된 모니터링 요청 전체를 `.wait()`할 수 있고, workflow에서 호출하면 그룹 취소와 오류 전파에 포함됩니다. 자동 60초 스케줄러는 같은 요청 생성 경로를 사용합니다. API 호출 시 이미 대기/실행 중인 모니터링은 중복 생성하지 않습니다.

## Operation 파일 원칙

버튼별 장비 작업은 독립된 Python 파일에 구현합니다. Reference Lock은 `configure_external_reference.py`, 내부 10 MHz는 `set_internal_reference_10mhz.py`, 내부 27 MHz는 `set_internal_reference_27mhz.py`를 실행합니다. 주파수와 위상 설정도 각각 `set_frequency.py`, `set_phase.py`로 분리합니다. 공유 operation 실행용 `support.py`나 `reference.py`를 두지 않습니다. 공통 acquire/assign과 실행 기반은 runtime에 유지합니다. 관측 목록과 초기 상태는 장비별 monitor가 담당합니다.

## 설정·workflow·모니터 책임

- `labremote/config/ramp.py`: ramp 설정 자료형. 실제 값은 operation 시작 시 고정한 장비 config에서 가져옵니다.
- `labremote/runtime/errors.py`: 일반 취소와 ramp 취소 예외.
- `labremote/runtime/workflow_runner.py`: 공통 API를 이용한 workflow 실행·완료 대기·오류 및 취소 처리.
- `labremote/devices/windfreak/monitor.py`: 관측할 항목 등록, 초기 미확인 상태, 60초 경과 항목 조회 예약과 모니터 요청 중복 방지. Worker는 예약된 operation의 큐 실행을 담당합니다. 초기 등록은 장비 I/O를 발생시키지 않으며 기존 관측값을 덮어쓰지 않습니다.

## 실행 책임 정리

- UI 상태 문구는 점유 상태를 바꾸지 않습니다. UI의 조작 가능 여부는 Worker의 대기/실행 상태 알림을 반영하며, 접수된 요청은 busy여도 공통 API를 통해 큐에 들어갑니다.
- UI 타이머와 workflow 모두 `WindfreakAPI.monitor()`를 사용합니다. 모니터는 매 스캔마다 최신 정책을 읽으며, 이미 큐에 들어간 요청을 제거하지 않습니다.
- `runner.py`가 설정 고정, 실행 기록, 오류/취소 알림, 완료 처리를 담당합니다. `ownership.py`는 operation 점유 획득과 해제만 담당하며 별도의 실행 스레드나 완료/취소 상태를 만들지 않습니다.
- `set_power.py`는 현재 파워를 acquire한 뒤 항상 ramp를 계산하고 실행합니다. Vpp 기준으로 config의 max_step_vpp 이하인 균등 단계로 나누고 각 단계마다 assign/readback 후 interval만큼 기다립니다. 목표값과 현재값이 같아도 한 번 assign/readback합니다. assign은 ramp를 계산하지 않고 해당 단계 값만 검증한 뒤 한 단계만 씁니다. RF OFF의 감쇠 ramp는 해당 operation 파일에서 독립적으로 구성합니다.
- Ramp 간격은 장비 config와 `PowerConfig`가 공통으로 사용하는 설정 검증을 따릅니다(유한한 0 이상의 초). operation에 별도의 0.2~5초 제한을 두지 않습니다.
- 상세 I/O 기록은 acquire/assign의 실제 get/set 경계에서 공통 실행 기록에 남깁니다. 기록 오류가 성공한 장비 쓰기를 실패로 바꾸지 않습니다.
- 바인딩은 `runtime/bindings.py`, 지원 장비/API는 `api/devices.py`에 통합했습니다. 이전 `configured.py`, `execution.py`, `request_validation.py`, `api/commands.py`, `api/instruments.py`는 제거했습니다.

Reference 변경은 RF/PA/PLL OFF 여부를 검사하지 않습니다. 외부 reference operation은 모드와 주파수를, 내부 10/27 MHz operation은 모드만 assign하며 각각 readback을 수행합니다. RF 출력 상태를 변경하지 않습니다. 주파수·위상·파워 변경도 RF 상태 검사나 live 변경 확인을 요구하지 않습니다.

Ramp 변환식은 set_power와 windfreak_off 내부에 직접 작성합니다. 50Ω 정현파 기준 `sqrt(0.4) * 10 ** (dbm / 20)`와 현재 dBm을 로그 밖으로 뺀 상대 전압 비율식을 사용하며 별도 변환함수를 호출하지 않습니다. assign은 ramp 옵션을 지원하지 않습니다.

`rf.acquire(path)`는 공통 실행 핸들을 반환하며, `.wait()`는 해당 요청이 실제로 읽은 값을 반환합니다. 읽은 값은 기존처럼 라이브러리와 UI에도 반영됩니다. 결과는 완료 신호 전에 핸들에 저장하며 실패·취소 시에는 값을 반환하지 않고 예외를 발생시킵니다. 예: `power = rf.acquire("channel_A.power_dbm").wait()`.


## SG384 · AnaPico · DDS

기본 탭은 `sg384_EA`, `sg384_EC`, `apsyn420_7g`, `dds4`입니다. 각 탭에서 Connect로 연결합니다. 실행 시 자동 접속·RF ON은 하지 않습니다. 서버 검색 또는 상단 장비 종류 선택과 이름 입력으로 추가할 수 있습니다.

```python
def main(devices):
    sg = devices.sg384('sg384_EA', port='N')  # BNC 또는 N
    power = sg.acquire('n_power_dbm').wait()
    sg.set_power(power).wait()  # 항상 ramp; 주파수와 위상은 두 출력 공통

    ana = devices.anapico('apsyn420_7g')
    hz = ana.acquire('frequency').wait()
    ana.set_frequency(hz).wait()
    # APSYN420은 고정 출력이므로 set_power가 없음

    dds = devices.dds('dds4', channel=1)
    dds.set_frequency(100e6).wait()
    dds.set_phase(0).wait()
    dds.set_vva(0).wait()
    # dds.on().wait()
    # dds.all_off().wait()
```

설정·검증 정책은 `labremote/config/{sg384,anapico,dds4}/`에 있습니다. UI와 workflow는 같은 API를 호출합니다. 장비마다 별도 worker와 소켓이 있으며, 공통 DeviceWorker/OperationRunner가 FIFO·점유·취소·timeout·알림을 처리합니다. 모니터링은 60초마다 실행하고 같은 파라미터의 모니터 요청만 중복 제거합니다.

Operation은 `labremote/operation/<family>/`에서 버튼별 독립 파일로 구성합니다. SG384 파워 제한(dBm/Vpp config)과 활성 출력의 주파수 대역 조건, AnaPico 고정 출력 최대값 정책은 assign에서 검사합니다. AnaPico 외부 reference는 주파수와 source를 assign/readback한 뒤 완료하며 lock을 기다리지 않습니다. lock 상태는 별도 acquire 또는 60초 모니터링으로 UI에 반영합니다. SG384 reference_events는 읽으면 지워지는 이력이라 수동 버튼으로만 조회합니다.

DDS 조회값은 **마지막 전송 설정**입니다. get/readback이 성공해도 실제 RF 측정을 의미하지 않습니다. 기존 DDS API v2의 get_status는 worker 안의 읽기 전용 status_json 어댑터로 acquire에 연결하며, 채널 요청은 QCoDeS get/set을 사용합니다. 미확인 값(None/-1)은 화면에 —/UNKNOWN으로 표시합니다. DDS Connect에서 서버 직렬 연결이 닫혀 있으면 기존 드라이버 connect를 호출합니다(드라이버가 전 채널 OFF/VVA 0으로 초기화). client Disconnect는 RPC 연결만 닫고 장비 disconnect를 호출하지 않습니다. 자동 저장값 복원이나 RF ON은 하지 않습니다.

모의 장비 검증과 실제 하드웨어 검증은 구분합니다. 실제 연결은 서버의 해당 장비 등록 및 기존 드라이버 파라미터가 필요합니다.


## OSA · MDT · FPGA · Motor (v6)

연결·수동 제어·반복 측정과 OSA–MDT PID, FPGA–Motor 자동 스캔을 지원합니다.

- mira → OSA (`aq6373`): 주파수 범위/표시 레벨/trace/auto reference, Zero, 단발·반복 스펙트럼 조회.
- mira → MDT (`mdt693b`): X/Y/Z 전압 설정·실제값 조회, master scan 설정, OSA PID 탭. PID는 Start를 눌러 시작합니다.
- others → FPGA (`fpga_local`): 기존 v5 로컬 COM 연결, 15개 출력, 4개 PMT 단발·반복 count 측정. COM 포트를 입력한 뒤 Connect하세요. Windows에 pyserial이 필요합니다. 기존 EC hardware definition을 그대로 사용합니다.
- others → Motor: EA/EC의 px/py/pz/sx/sy/sz 12개 행과 모터별 worker/FIFO를 유지합니다. 서버 USB에 연결한 KDC101을 QCoDeS/InstrumentServer(기본 5555)로 제어합니다. 시리얼 번호는 서버 드라이버에 설정합니다.

모든 설정은 `labremote/config/{osa,mdt,fpga,motors}/`에 있습니다. OSA·MDT는 기존 InstrumentServer 호스트 설정을 사용합니다. FPGA는 COM 연결, Motor는 12개 행이 공통 서버 연결 설정을 사용하며 실행만으로 연결하거나 출력을 변경하지 않습니다.

UI와 workflow는 `devices.osa()`, `devices.mdt()`, `devices.fpga()`, `devices.motor()`의 공통 API를 사용합니다. 버튼별 operation은 `operation/<family>/`의 독립 Python 파일입니다. MDT의 서버/장비/클라이언트 전압 제한과 Motor 이동 범위는 assign에서 검사합니다. OSA trace 디코딩·배열 검증은 acquire에서 수행합니다. FPGA 하위 드라이버의 시리얼 프레임·FIFO 검사와 장비 실행 완료 확인은 기존 프로토콜 처리를 유지합니다.

OSA `sweep_start`와 `zero_once`는 `operation_complete`를 readback으로 사용합니다. 반복은 장비별 별도 스레드에서 단발 API 완료를 기다린 뒤 다음 측정을 요청합니다. 취소는 진행 중인 assign/readback을 마친 뒤 적용됩니다. 진행 중인 OSA 완료 응답은 장비 timeout까지 기다릴 수 있습니다. Stop repeat/Cancel은 이어서 독립 ABORT 요청을 큐에 넣습니다. 통신 오류로 장비의 active 상태가 남았다면 연결 상태를 확인하고 Abort 후 재시작하세요. OSA 자체 통신 timeout보다 여유 있는 클라이언트 timeout(기본 95초)을 쓰며 소켓 재생성 후에도 이 값을 유지합니다.

Motor의 Cancel은 진행 중인 이동 명령을 물리적으로 중단하는 기능이 아닙니다. 합의한 assign 완료/readback 이후 취소를 적용하며, Stop 버튼도 동일 FIFO에 들어갑니다. 모터 position은 mm이며 서버 드라이버와 클라이언트 범위는 0–12 mm입니다. 모니터링과 별도로 명시적 status/acquire는 서버에 새 요청을 보냅니다. timeout 후 원래 명령을 재시도하지 않으며 다음 요청을 위해 새 세션을 생성합니다. 연속 timeout은 연결 오류로 전환합니다.

FPGA는 REQ 소켓 대신 원시 시리얼 스트림을 사용하므로 timeout 뒤 부분 응답을 다음 요청에 섞지 않도록 연결을 닫고 수동 재연결을 요구합니다. 일부 slow-port 출력은 하드웨어 readback이 없어 UI에 Unknown으로 표시합니다. 해당 set의 성공은 전송 완료이며 물리적 ON 확인이 아닙니다. 반복 취소 시 counter disable/stop 정리는 기존 드라이버가 수행합니다.

```python
def main(devices):
    spectrum = devices.osa('aq6373').read_spectrum().wait()
    voltage = devices.mdt('mdt693b').acquire('x.voltage').wait()
    counts = devices.fpga('fpga_local').measure(0, 100).wait()
    position = devices.motor('EA_px').status().wait()['position']
```

각 장비별 `read_osa.py`, `read_mdt.py`, `read_fpga.py`, `read_motor.py` 예제를 workflow 편집기에서 선택할 수 있습니다. 로컬 테스트에서는 실제 장비 연결·전압 변경·모터 이동을 수행하지 않았습니다.

장비 수가 늘어나도 각 operation마다 모든 YAML을 다시 파싱하지 않도록 내용 기반 파싱 캐시를 사용합니다. 파일 내용은 매번 다시 읽고 operation별 복사본을 만들어, 실행 시작 시 config 고정 및 다음 operation에서의 변경 반영 원칙을 유지합니다.


## OSA–MDT PID와 FPGA–Motor 스캔

mira → MDT → OSA PID에서 OSA 소스와 축, 목표 주파수·PID 계수·평균 횟수를 지정합니다. 먼저 OSA 반복 측정을 시작해야 합니다. 시작 전 캐시와 단발 조회는 피드백으로 사용하지 않고, 같은 반복 실행에서 새로 얻은 스펙트럼만 사용합니다. 선택적으로 sech² peak fit을 사용하며, 신호 세기·SNR·capture 범위와 전압·step·slew 제한, 적분 누적 제한을 유지합니다. 기본 목표와 계수는 0이므로 실제 값을 설정해야 합니다.

잘못된 스펙트럼은 HOLD하며 새 정상 데이터가 최대 간격 이내에 도착하지 않으면 실패합니다. OSA 반복 중단·연결 해제·취소 시 PID가 중단되며 마지막 전압을 유지합니다. 이전 전압으로 자동 복구하지 않습니다. 실행 중 목표와 계수는 Apply로 변경합니다. 설정은 labremote/config/devices/mdt/device_config.yml의 pid_defaults에 있습니다.

others → FPGA → Scan 1–4에서 X/Y 모터, PMT, 절대 시작·끝 좌표·step, 노출·평균·안정화 시간을 설정합니다. 현재 위치를 더하지 않고 입력 좌표 자체로 이동합니다. 예: 시작 5990, 끝 6010, step 1 µm는 서버에 5.990–6.010 mm를 요청합니다. Y를 바꾼 뒤 X를 오름차순으로 이동하는 raster 방식입니다. 기본 단위 환산은 서버 1단위당 1000 µm입니다. QCoDeS position 파라미터는 mm입니다. FPGA 반복 측정과 스캔은 동시에 실행하지 않습니다.

이동과 측정은 공통 API/FIFO를 사용합니다. 이동 operation의 assign readback과 상태 조회로 위치를 확인합니다. 측정 직전·직후의 추가 위치 조회는 하지 않습니다. CSV의 actual 위치는 마지막 이동 후 조회값입니다. 이동 readback 불일치·통신 오류가 있으면 중단합니다. 수동 요청은 operation 사이에 들어갈 수 있으므로 스캔 중 위치를 변경하지 마세요. Stop은 진행 중 요청/readback 이후 적용되며 물리적 비상 정지가 아닙니다. 취소·오류 시 두 모터에 Stop을 요청하고 부분 결과를 저장합니다. 시작 위치로 자동 복귀하지 않습니다.

각 실행 폴더에 configuration.json, points.csv, heatmap.npz, heatmap.png, result.json을 저장합니다. 완료 시 2D Gaussian fit의 중심·coupling MFD·오차·R²를 표시합니다. 데이터가 부족하거나 fit이 실패해도 측정 결과는 보존됩니다. 앱 종료는 자동 작업 중단과 부분 저장이 끝난 후 연결을 닫습니다.

UI와 workflow 모두 start_pid()/start_scan() 공통 실행 핸들을 사용합니다. 별도 작업 스레드가 개별 operation의 wait()를 순서대로 기다리며 장비 worker를 직접 우회하지 않습니다. workflow 예제 mdt_pid.py와 fpga_motor_scan.py를 참고하세요. PID는 취소할 때까지 실행되므로 해당 핸들의 wait()도 계속 대기합니다. scipy가 필요하며 requirements_client.txt에 포함되어 있습니다.


### 통합 Motor 탭과 서버 설정

모터 탭에는 별도 Host/Port 입력이 없습니다. Connect server를 누르면 메인 화면 상단의 공통 Host/Port를 사용합니다. 각 행의 Step은 µm이며 −/+ 버튼은 큐에서 실행될 때 현재 위치를 acquire하고 step만큼 이동합니다. workflow에서도 `motor.move_relative(0.001).wait()`로 +1 µm 이동할 수 있습니다(API 단위는 mm).

Open all / Close all / Home all은 연결된 모터들을 표시 순서대로 공통 API로 하나씩 실행합니다. 오류가 나면 뒤의 모터는 실행하지 않습니다. 참여 모터의 Cancel은 전체 작업을 취소하며, 진행 중 assign/readback은 완료한 뒤 중단합니다. Disconnect 및 앱 종료도 기존 공통 취소 경로를 사용합니다. Home all이 USB를 자동으로 열지는 않으므로 Open all을 먼저 실행하세요.

others → Motor의 한 화면에 12개 모터를 표시합니다. 공통 Host/Port는 모터를 USB로 연결한 Linux InstrumentServer PC의 주소(기본 포트 5555)입니다. Client ID/Token/owner 중계 연결은 사용하지 않습니다. 각 행의 Instrument는 서버에 등록된 EA_px, EA_py, …, EC_sz입니다. 각 worker가 자체 InstrumentServer REQ 소켓과 operation FIFO를 사용합니다.

Actual/Target은 µm, 서버 position과 workflow move()/acquire('position')는 mm입니다. 12000 µm = 12 mm이며 입력 범위는 유지합니다. Read와 Read all positions는 status 파라미터를 새로 acquire하며 조회 실패는 Unknown으로 표시합니다. 60초 모니터링도 같은 API를 사용합니다.

서버 배치 파일은 로컬 전용 server_deploy_latest/KDC101/입니다. Git clone에는 없으므로 필요하면 별도로 직접 전달받으세요. 드라이버 옆 serials.local.json에 실제 시리얼 번호를 보관하고 serverConfig.example.yml의 항목을 서버의 기존 instruments 아래에 합친 뒤 해당 initialize를 true로 변경하세요. serials.local.json은 Git에서 제외되며 서버 PC로 직접 복사합니다. 시리얼 번호는 UI에 저장하지 않습니다. 자세한 설치 및 단위 설정은 같은 폴더의 README_KO.md를 참고하세요.

Connect는 서버 파라미터에 연결하며 USB를 자동 Open/Home/Move하지 않습니다. 최초 사용은 Open을 누르세요. UI Disconnect와 앱 종료는 클라이언트 소켓만 닫으며 USB 모터를 Close하거나 위치를 바꾸지 않습니다. Close 버튼은 USB 핸들을 닫고, 서버 종료의 드라이버 정리도 USB 핸들을 닫습니다.

모터의 클라이언트 응답 제한은 config/devices/motors/device_config.yml의 timeout_s=210초, 서버 하드웨어 이동 제한은 180초입니다. 통신 timeout 시 소켓 재생성만 하며 이동 명령을 재전송하지 않습니다. 재생성 후에도 응답이 없으면 연결 오류로 전환하고 수동 재연결합니다. 서버 내부 하드웨어 이동 제한에 도달하면 Stop을 한 번 요청하고 실패를 반환합니다.

InstrumentServer의 단일 요청 처리 루프에서는 모터 이동 완료를 기다리는 동안 다른 서버 요청도 대기합니다. Scan 1–4의 독립 runner/FPGA 큐 구조는 유지하지만, 기존 중계 서버와 동일한 모터 동시 처리 성능을 보장하지 않습니다. Stop/Cancel도 진행 중 assign 이후 적용되는 기존 정책이며 즉시 USB 정지가 아닙니다.

스캔 설정 키 x_start_um/x_stop_um/y_start_um/y_stop_um은 이제 절대 좌표입니다. 예전 상대 offset을 넣은 사용자 workflow 파일은 절대 좌표로 변경해야 합니다. 새 저장 파일에는 coordinate_mode: absolute와 x_positions_um/y_positions_um을 기록하며 CSV와 그래프도 절대 좌표를 표시합니다.


### Scan 1–4 동시 실행

각 Scan은 독립 runner/스레드와 취소 그룹을 가집니다. 개별 Start 또는 FPGA의 Start all scans로 함께 시작합니다. 각 runner는 모터 이동 → 이동 readback/상태 조회 → settle → FPGA measure API를 순서대로 기다립니다. FPGA는 measure operation(채널 설정·노출 설정·측정·정리) 동안만 점유하며 모터 대기 중에는 다른 Scan의 측정을 처리합니다. 대기 중인 요청은 FIFO 순서이고 강제 1→2→3→4 순환은 아닙니다. 평균 N회도 한 회씩 큐에 넣어 완료를 기다립니다.

같은 모터를 공유하는 Scan은 동시에 시작하지 못합니다. 서로 다른 모터 조합은 하나의 FPGA를 공유할 수 있습니다. 별도의 FPGA 연속 측정은 스캔이 모두 끝난 뒤 시작합니다. 측정 전후 수동 위치 변경 감시는 제거했으므로 스캔 중인 모터를 수동으로 움직이지 마세요.

UI에서 독립적으로 시작한 Scan은 개별 Stop/일반 오류 시 해당 Scan만 중단합니다. Stop all scans 또는 FPGA Cancel/연결 해제는 전체 Scan을 중단합니다. 같은 사용자 workflow 안에서 시작한 Scan들은 기존 workflow 취소 그룹을 공유하므로 하나의 실패나 workflow 취소가 전체에 적용됩니다. 부분 저장·연결 해제·앱 종료 정책은 유지합니다.

각 operation 실행 핸들에는 scan 번호와 scan_run_id가 기록되고 결과는 그 핸들을 기다리는 runner로 반환됩니다. 모터는 장비별 InstrumentServer REQ/REP 요청으로 응답을 구분합니다. 서버가 runner를 기억하도록 변경할 필요는 없습니다. FPGA는 로컬 COM 장비이며 하나의 worker가 측정과 결과 읽기를 마칠 때까지 다음 측정을 시작하지 않습니다.

workflow 예제 fpga_motor_scans.py는 네 Scan을 먼저 시작한 뒤 각각 wait()합니다. start_scan(...).wait()를 네 번 연속 쓰면 순차 실행이므로 이 차이를 확인하세요.


### Z축 스캔과 MFD 타원 표시

각 Scan 탭의 Enable Z scan을 켜면 Z 모터와 절대 시작·끝·step(µm)을 지정할 수 있습니다. 기본 Z 모터는 Scan 1=EA_pz, 2=EC_pz, 3=EC_sz, 4=EA_sz입니다. 끄면 기존 XY 스캔이며 Z 모터는 움직이지 않습니다. 켜면 Z 바깥 루프 → Y → X 순서로 각 Z에서 XY 평면을 측정합니다. 전체 XYZ 격자는 최대 100000점이고 Z를 공유하는 두 Scan은 동시에 실행하지 못합니다. Z도 이동 readback/상태 조회만 사용하며 측정 전후 추가 조회는 하지 않습니다.

View Z plane으로 평면을 선택합니다. Follow current Z가 켜져 있으면 진행 중인 평면을 따라갑니다. 완료 시 타원형 Gaussian의 X/Y MFD를 추정하고 흰 실선으로 타원의 1/e² 경계를 표시합니다. X/Y 폭은 각각 유지하며 평균 원은 표시하지 않습니다. R²와 경고는 타원 피팅 결과입니다. 이는 측정된 coupling profile의 유효 지름이며 광학 보정 없이 fiber 자체의 MFD로 단정하지 않습니다.

XYZ 결과 heatmap.npz의 counts는 [Z,Y,X], z_um은 Z 절대 좌표입니다. 기존 XY의 counts는 [Y,X]를 유지합니다. points.csv에는 Z 좌표·이동 후 조회값이 추가되며 result.json의 z_fits에 평면별 타원 피팅 정보를 저장합니다. heatmap_z_0000.png 등의 파일에 측정한 평면을 저장하고 heatmap.png는 마지막 측정 평면입니다. 취소 시 미측정 값은 NaN으로 보존하고 완료 피팅을 하지 않습니다. 미측정 평면의 PNG는 만들지 않습니다.

workflow에서 start_scan(x, y, settings, z_motor=z)로 Z를 추가합니다. fpga_motor_scan_xyz.py 예제를 참고하세요. Z를 생략하면 기존 XY workflow가 그대로 동작합니다.


### FPGA Manual 스위치와 Input counts

Manual 스위치는 이름과 상태가 들어 있는 단일 버튼입니다. 초록색은 ON, 빨간색은 OFF, 회색은 Unknown/Pending이며 클릭하면 반대 상태를 요청합니다. 스위치 표시는 UI/workflow 공통 파라미터 라이브러리의 최신 요청·조회 결과를 사용합니다. 물리적 readback이 없는 출력은 라이브러리에 기록된 성공한 요청 상태를 ON */OFF *로 구분합니다. 최신 전체/개별 조회 실패 시 이전 상태를 재사용하지 않고 Unknown으로 표시하며, 새 조회가 성공하면 복구합니다. 연결 해제 시 상태를 Unknown으로 되돌립니다.

Input counts 탭에서 입력 포트, Exposure(ms), Average(1–1000), 점 사이 대기 시간을 지정합니다. Start는 기존 FPGA 반복 runner를 통해 공통 API/큐를 사용합니다. 각 점은 Average 횟수의 독립 노출 광자수 평균입니다. 그래프에는 최근 20개 점만 남고 Save CSV log를 켜면 모든 점의 UTC 측정 완료 시각, 경과 시간, 채널, 실제 노출 시간, 평균 횟수, 평균/합계 광자수를 기록합니다. 기본 저장 위치는 logs/fpga_counts이며 실행마다 새 파일을 만듭니다. Stop·오류·연결 해제·앱 종료 시 반복을 중단합니다. 로그 저장 실패도 반복을 중단합니다. 기존 정책에 따라 연속 입력 측정과 모터 스캔은 동시에 시작하지 않습니다. Scan 1–4 탭은 유지합니다.

workflow에서도 `fpga.measure_counts(channel=0, exposure_ms=100, average=10).wait()`로 같은 평균 결과를 얻을 수 있습니다. 기존 `measure()` 및 스캔의 단일 측정 동작은 유지합니다.
