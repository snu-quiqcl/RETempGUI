# 탭 설정 저장·복원 및 다른 PC 업데이트

현재 설정 파일 이름과 .local 통합 절차는 [설정 안내](../CONFIGURATION.md)를 기준으로 합니다. 아래 과거 이전 기록과 구분하세요.

## 실제 저장 위치

모든 경로는 RETempGUI 저장소 기준이다. `labremote/config`, `labremote/data`, 로그 폴더는 Git에서 제외한다.

| 내용 | 경로 |
| --- | --- |
| 장비 탭의 마지막 편집값 | `labremote/config/ui/tabs/<family>/<device_id>.json` |
| 실험 탭의 마지막 편집값 | `labremote/config/ui/tabs/experiments/<group>/<page>/<fpga_id>.json` |
| CCD·Workflow·Queue·Monitor·Flipper·공통 화면 | `labremote/config/ui/tabs/common/<root>.json` |
| 기존 공통 저장값 | `labremote/config/ui/input_state.json` — 읽기 전용 이전 원본 |
| 처음 사용하는 입력의 기본값 | `labremote/config/ui/input_defaults.json` |
| 실험·DAC 타이밍 기본값 | `labremote/config/operations/defaults/*.json` |
| Oven 선택·전압·전류·ramp/OFF 설정 | `labremote/config/operations/oven.json` |
| 명시적으로 저장한 실험 preset | 기존 `labremote/config/operations/...` 및 `devices/fpga/settings/<fpga_id>/...` |
| Two-RF preset | 기본 FPGA: `operations/micromotion/<EA\|EC>.two_rf.json`; 추가 FPGA: `devices/fpga/settings/<fpga_id>/micromotion/...` |
| DAC preset·시퀀스 파일 | `labremote/config/presets/dac/`, `labremote/config/sequences/dac/` |
| 저장한 Queue plan | `labremote/config/queues/` |
| 보정 원본 및 복원용 불변 사본 | `labremote/data/calibration/`, `labremote/data/calibration/ui_snapshots/` |
| 실행 결과·로그 | 기존 `labremote/data/` 하위 |

보고서의 제안 경로를 모두 새로운 운전 파일로 중복 생성하지 않고, **마지막 편집 상태**와 **사용자가 저장한 재사용 preset**을 구분했다. Queue의 자동 draft는 `ui/tabs/common/queue_tab.json`의 models에 저장된다. CCD의 acquisition/detection/view도 같은 방식으로 `ccd_tab.json`에 모인다. 기존 전문 preset 파일은 그대로 남고 Load/Save 기능도 유지한다. Phase Hold/Rabi/Ramsey/SPAM 2D의 Save 기본 경로도 선택한 FPGA로 분리하며, 보정 Ramsey는 `ramsey_calibrated.json`을 사용한다.

숫자·문자열·선택·단위·체크박스·편집 가능한 표를 저장한다. 큐의 작업/그룹/반복/parameters/동결된 소스와 핀 매핑, DAC 시퀀스 행, 보정표 선택과 사용 여부, π/2 보정 결과 참조, CCD 보기 영역, 페이지별 FPGA 선택을 함께 저장한다. 탭 자동복원용 보정 원본은 data에 보존하고 config에는 경로와 SHA256을 기록한다. 기존 수동 preset과 Queue의 동결된 실행 조건은 재현성을 위해 기존 형식을 유지한다. 결과 표, 로그, 비밀번호, Python 소스 편집기는 일반 입력 저장 대상에서 제외한다. 소스 편집은 기존 Save/Cancel 절차를 유지한다. 장비·핀 매핑 편집 대화상자도 기존 Save/Cancel이 적용된다.

## 우선순위와 보존

1. 해당 탭의 마지막 편집값이 있으면 복원한다.
2. 없으면 기존 `input_state.json`의 값을 읽는다. 숫자 슬롯 키도 새 페이지 식별자로 연결한다.
3. 둘 다 없으면 로컬 `input_defaults.json` 및 해당 장비/실험의 로컬 기본값을 사용한다.
4. 사용자가 preset을 Load하면 그 값이 현재 편집 상태가 되고 다음 저장에 반영된다.

기존 공통 파일은 수정하지 않는다. 미방문 탭과 알 수 없는 저장 키도 삭제하지 않는다. FPGA를 바꿀 때 다른 FPGA의 전압·조건을 복사하지 않는다. 추가 FPGA의 Two-RF preset이 없을 때만 기존 chamber preset을 검증해 읽는다. 이후 Save는 해당 FPGA의 경로로 분리된다.

약 1.5초 간격 및 정상 종료 시 저장한다. 파일마다 임시 파일을 쓴 뒤 교체하며 내용이 같으면 쓰지 않는다. 외부 편집이나 다른 창의 저장이 감지되면 해당 상태 저장을 중단하고 기존 파일을 유지한다. 손상된 JSON이나 범위를 벗어난 값도 임의로 덮어쓰지 않는다. 범위 오류는 사용자가 입력칸을 수정해 편집 완료한 후 다시 저장할 수 있다.

복원 시 입력 신호를 차단한다. 저장값 복원은 장비 연결·DAC 인가·RF 출력·실험 실행을 호출하지 않는다. 실제 운전은 기존 연결/Apply/Run 조작으로 실행한다.

## 다른 PC: pull 전에 해야 하는 일

이 절차는 **업데이트할 PC에서** 수행한다. 이 PC의 config를 다른 PC에 덮어쓰면 안 된다.

1. 앱과 실험을 종료한다. 저장소 밖에 기존 저장소 전체를 백업한다. 최소한 config/data/logs/사용자 workflow, 수정한 Python 파일, `git diff --binary HEAD`, Git 상태와 현재 HEAD를 보관하고 복사 해시를 검증한다.
2. 이번 변경의 `tools/export_local_defaults.py` 하나를 저장소 밖에 복사한다. **pull 전의 기존 코드와 기존 Python 환경**에서 실행한다.

   ```powershell
   python -B D:ackup\export_local_defaults.py --repo D:\path	o\RETempGUI
   ```

   이 도구는 그 PC의 기존 실험 기본값·Oven profile·DAC 타이밍을 `config/operations/defaults`로 내보낸다. 이미 있는 파일은 덮어쓰지 않는다. 장비를 연결하지 않는다. 오류가 나면 업데이트하지 말고 기존 코드에서 해당 값을 확인해 내보낸다. 구버전 코드의 구조가 다르면 수정 파일 백업을 유지한 채 별도 이전이 필요하다.
3. 내보낸 config를 저장소 밖 백업에도 추가한다. `git status --short`에서 아직 추적되는 로컬 변경을 확인한다. **코드 수정도 별도 보존한 뒤** working tree를 정리해야 pull할 수 있다. 이 변경이 다른 PC의 미커밋 파일을 자동으로 정리하지는 않는다. 강제 reset/clean으로 해결하지 않는다.
4. 업데이트 후 그 PC의 config/data를 복원한다. 과거 추적 파일이 삭제되는 최초 업데이트에는 특히 이 단계가 필요하다. 기존 장비 주소·핀·전압을 다른 PC의 값으로 교체하지 않는다.
5. 시작 전 아래 명령으로 config/data/logs가 추적되지 않는지 확인한다. 첫 명령은 출력이 없어야 한다.

   ```powershell
   git ls-files -- labremote/config labremote/data data logs
   git check-ignore labremote/config/ui/input_state.json labremote/data/calibration/ui_snapshots/probe.json
   ```

6. 앱을 시작해 저장값을 확인하고 일부 설정 변경 후 종료한다. `git status --short`를 이전 상태와 비교한다. config가 바뀌어도 Git 추적 파일은 새로 변경되면 안 된다. 기존의 실제 코드 수정은 별도로 남을 수 있다.

## 오프라인 검증

`python -B -m unittest checks.test_tab_settings`는 손상·범위 오류·외부 변경·장비명 충돌·이전 값 보존을 검사한다.
`python -B checks/verify_all_tab_settings.py`는 실제 config를 임시 디렉터리로 복사하고 장비 접속을 차단한 채 모든 장비 family와 31개 실험 페이지를 생성한다. 입력과 복합 모델을 바꾸고 창을 종료·재생성해 복원을 비교한다. 실행 전후 Git 추적 파일 및 실제 config의 SHA256이 동일해야 통과한다. 실장비 동작 검증은 수행하지 않는다.


## 이번 변경의 검증 기록 (2026-11-22)

- 변경 전 백업: `D:\coding\QCODES\RETempGUI-local-backups\20261122-150745` (5,337개 파일, SHA256 확인).
- 기존 config/data/logs 4,552개 파일: 변경 후에도 원본 해시 일치. 추가된 기본값 profile 30개는 기존 Python 값을 내보냈으며 기존 JSON을 덮어쓰지 않았다.
- 전체 창: 31개 실험 페이지, 모든 장비 family, 입력 1,388개를 생성. 수치 788개, 선택 285개, 체크 87개, 텍스트 8개와 복합 모델 8개를 변경하고 종료·재생성해 복원 확인. 불일치 및 복원 대기 항목 0개.
- 예전 per-device FPGA 저장 키의 숫자 284개가 현재 페이지에 같은 값으로 복원됨을 별도 확인.
- 큐 그룹·동결 parameters, DAC 시퀀스, 두 FPGA의 별도 Rabi 값, 보정표·π/2 데이터 참조 및 CCD 보기 범위 포함. 복원 중 장비 연결 차단.
- 전체 창 테스트 전후 Git 추적 파일 및 실제 config 해시 동일. 초기 파일 구성 직후 저장 약 1.17초, 구조가 유지된 상태의 저장 약 0.17초 (모든 탭을 동시에 생성한 검증 환경).
- 저장/복원·Two-RF·로컬 저장소 회귀 검사 41개 통과 (수동 preset의 FPGA별 경로 검사 포함). `git diff --check` 통과. config/data/logs Git 추적 파일 0개.
- 임시 두 체크아웃에서 서로 다른 PC 값과 Python 안의 사용자 타이밍을 내보내고 새 코드로 교체한 뒤 동일 값 확인. 재내보내기도 기존 파일을 수정하지 않음. 실제 pull/commit은 수행하지 않았다.
- 기존 전체 실험 테스트는 모두 통과한 상태가 아니다. 별도 확장 실행에서 instrumentserver import 환경 및 FPGA 매핑 전제 때문에 실패가 있었다. Secular/Phase-Ion 23개를 변경 전 HEAD와 변경 후 복사본에서 동일하게 실행했을 때 실패/오류 항목이 일치했다. 이 작업에서 실장비 측정이나 기존 매핑 테스트 정비는 수행하지 않았다.

재검증 명령:

```powershell
python -B -m unittest checks.test_tab_settings tests.test_ui_input_state tests.test_input_defaults tests.test_two_rf_analysis tests.test_two_rf_workflow tests.test_config_layout tests.test_local_storage
python -B checks/verify_all_tab_settings.py
python -B checks/verify_update_preservation.py
```

마지막 스크립트의 이전 코드 기준은 현재 변경 전 HEAD다. 이번 변경을 나중에 커밋한 뒤에는 이전 revision fixture를 별도로 지정하도록 갱신해야 한다. `tests/`의 기존 검사는 일부 로컬 보관 파일이므로 다른 PC에 없을 수 있다. 이번에 추가한 `checks/`와 `tools/`는 Git에 포함할 수 있는 코드이며 실제 설정 파일은 포함하지 않는다.


## 서버 IP의 기준과 localhost 재복원 수정 (2026-11-22 후속)

InstrumentServer 접속 주소의 기준 파일은 `labremote/config/devices/connections.json`이다. `server_host`에는 InstrumentServer가 실행되는 PC의 IP/호스트명, `server_port`에는 해당 포트를 지정한다. `127.0.0.1`은 클라이언트 자신이므로 서버도 같은 PC에서 실행할 때만 사용한다.

- 로컬 파일이 없을 때만 `devices/connections.json`의 명시된 주소를 읽는다. 활성 파일에 host/port가 없으면 설정 오류를 표시하며 임의의 localhost 기본값으로 연결하지 않는다.
- UI에서는 **연결 설정 → Host / Port**를 편집한 뒤 Enter 또는 다른 입력칸으로 이동하면 같은 연결 파일에 저장한다. Rescan과 정상 종료 때도 미저장 변경을 반영한다. 기존 motor 설정은 유지한다.
- `ui/client_settings.json`, `ui/client_settings.json`, `ui/input_defaults.json`, `ui/input_state.json`, `ui/tabs`의 값은 서버 주소를 덮어쓸 수 없다. 이 PC의 오래된 중복 서버 키는 아래 백업 후 제거했다. 다른 PC에 중복 키가 남아 있어도 새 코드에서는 접속 입력칸의 일반 UI 복원을 비활성화하므로 무시한다.
- 명령줄 `--host` / `--port`는 해당 실행의 명시적 override다. UI에서 추가로 편집하지 않고 종료하면 연결 파일에 저장되지 않는다. 포트 범위 오류는 입력 위젯에 의해 다른 값으로 바뀌기 전에 거부한다.
- 파일을 직접 편집했다면 앱을 다시 시작한다. 다른 창이나 외부 편집과 충돌하면 기존 파일을 덮어쓰지 않고 저장 오류를 표시한다.
- 현재 통합 GUI의 Motor 연결도 공통 InstrumentServer 주소를 사용한다. 기존 `motor_host` / `motor_port`는 호환 설정으로 보존하며 이 GUI의 서버 Host를 바꾸는 항목이 아니다.

문제 원인: 올바른 연결 파일을 읽어 Host를 만든 다음, 일반 입력 상태 복원이 옛 `127.0.0.1`을 Host 입력칸에 다시 썼다. 실제 접속 함수는 이 입력칸을 읽어 잘못된 주소로 검색했다. 단순 값 round-trip 검증만으로는 이 우선순위 오류를 발견하지 못했다.

추가 검증에서 빈 Queue의 실행용 plan 검증이 공통 UI 저장을 막는 문제도 발견했다. 실행 가능한 Queue 검증은 그대로 유지하면서 빈 목록을 저장 가능한 초안으로 처리하도록 수정했다.

백업: `D:\coding\QCODES\RETempGUI-local-backups\server-endpoint-20261122-160049`.
실제 연결 파일(서버/모터 주소 포함)은 수정 전과 SHA256이 같다. 이번에 바뀐 로컬 값은 오래된 UI 중복 서버 키의 제거뿐이다.
관련 회귀 검사 29개 통과. 실제 Window 생성·종료를 세 번 수행해 stale localhost 무시, 편집값의 재시작 복원, 일회성 CLI override, 실제 검색 요청에 전달되는 endpoint, 빈 Queue 저장을 확인했다. 장비 연결은 차단했고 테스트 전후 실제 config 및 Git 추적 파일 해시는 동일했다.

```powershell
python -B -m unittest checks.test_connection_settings checks.test_tab_settings tests.test_ui_input_state tests.test_input_defaults
python -B checks/verify_connection_restart.py
```

다른 PC에서는 이번 **코드 변경도 반영한 뒤 앱을 재시작**해야 한다. 구버전 코드에서는 연결 파일만 바꿔도 옛 UI 상태가 다시 덮어쓸 수 있다.
