# Motor UI와 Backlash

Motor/Instrument는 한 열입니다. 표시 이름은 서버 연결 이름이며 연결 해제 상태에서 변경할 수 있습니다. 기존 논리 축(EA_px 등)은 tooltip에 표시되고 scan 매핑은 유지됩니다. EA/EC collection/excitation별로 묶어 표시합니다.

- 이동: Actual, Target, Step(µm), −/Move/+.
- Device: Read, Home, Stop. ⋯ 메뉴에는 Open, Close, Cancel.
- 오른쪽 Backlash: Actual(현재 읽은 값), Set(설정할 값), Read, Apply.
- 먼저 Connect와 Open을 수행하세요. Open은 ⋯ 메뉴 또는 Open all입니다.
- Apply는 µm 입력을 mm로 변환해 기존 operation 큐에 제출하고 readback을 확인합니다. 연결 시 자동 설정하지 않으며 자동 polling에도 backlash 쿼리를 추가하지 않습니다.
- Actual의 —는 미조회/실패/연결 해제 상태입니다. Set의 초기 0은 실제 측정값이 아닙니다. 먼저 Read로 확인하세요.
- 모터 이동/홈 중 서버의 설정 변경을 거부합니다. UI에서는 작업이 진행 중이면 Backlash Read/Apply를 비활성화합니다.
- Backlash는 컨트롤러 설정입니다. 이동 코드에 별도 왕복 보상을 추가하지 않았습니다. 재부팅 후 영구 보존을 보장하거나 flash 저장 명령을 실행하지 않습니다.

서버 파라미터는 `backlash`(mm)입니다. 기존 `units_per_mm`를 그대로 사용합니다. 입력 범위는 드라이버의 이동 범위 폭에 대해 ±값이며, 클라이언트 상한은 ±12 mm입니다. readback 허용 오차는 0.00003 mm(0.03 µm)로 기본 34304 units/mm에서 한 카운트 반올림/절삭을 허용합니다. 다른 환산값을 사용하는 경우 장비 분해능과 registry 오차를 함께 검토하세요.

기존 서버 드라이버에는 backlash가 없으므로 서버 파일도 교체해야 합니다. 교체 전에도 기존 이동 기능은 유지되지만 Backlash Read/Apply는 지원되지 않습니다.

## 옮길 파일

기준 로컬 루트: `D:\coding\QCODES\RETempGUI\RETempGUI\RETempGUI`

서버 PC: `server_deploy_latest/KDC101/KDC101.py`를 서버에서 사용 중인 `KDC101/KDC101.py`에 덮어쓴 뒤 InstrumentServer를 재시작합니다. 기존 배치 구조라면 `/home/quiqcl-ent/server/qcodes-driver/qcodes_driver/KDC101/KDC101.py`가 대상입니다. YAML의 `type`과 실제 import 경로를 확인하고 해당 파일을 교체하세요. `__init__.py`와 서버 YAML의 장비 이름·시리얼·units_per_mm은 유지합니다. 시리얼은 드라이버 내부 `SERIAL_NUMBERS`에서 관리하며 별도 JSON 파일은 필요하지 않습니다. 기존 pylablib 1.4.5/pyserial 의존성을 사용하므로 새 패키지는 필요하지 않습니다.

UI PC: 다음 파일을 같은 상대 경로로 복사하고 GUI를 재시작합니다.

1. `labremote/ui/motor_tab.py`
2. `labremote/api/devices.py`
3. `labremote/config/operations/motors/parameter_registry.yml`

서버 드라이버 폴더는 Git에서 제외되어 있으므로 서버 파일은 직접 전달해야 합니다. UI PC는 변경을 commit/push한 뒤 pull해도 됩니다. 이번 변경은 자동 commit/push하지 않습니다.

Workflow 사용 예:

```python
motor = devices.motor('EA_px')
current_mm = motor.read_backlash().wait()
motor.set_backlash(0.010).wait()  # 10 µm, 서버 API 단위는 mm
```

구현은 pylablib의 [get_gen_move_parameters / setup_gen_move](https://pylablib.readthedocs.io/en/stable/_modules/pylablib/devices/Thorlabs/kinesis.html)를 사용합니다. 실제 USB 장비에서의 동작 확인은 별도로 필요합니다.
