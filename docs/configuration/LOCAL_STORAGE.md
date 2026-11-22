# PC별 설정·데이터 보존과 업데이트

## 저장 위치와 Git

저장소 기준 상대 경로:

```text
labremote/
  configuration/                   # Git 추적: 설정 읽기/검증/명시적 이전 코드
  config/                          # 전체 Git 제외: 이 PC의 실제 설정
    devices/                       # 연결 주소, 장비 정책, DAC map
    operations/micromotion/        # EA.two_rf.local.json / EC.two_rf.local.json
    ui/                            # UI 기본값·입력 상태·장비 구성
    presets/dac/{EA,EC}/
    sequences/dac/{EA,EC}/
    queues/                        # 저장한 queue plan
    examples/                      # 기존 JSON/YAML 예제 설정도 로컬 보관
  data/                            # 전체 Git 제외
    calibration/phase_shifter/      # 보정 원본 CSV/JSON
    logs/operations/               # 실행 기록 (동결된 configuration.json 포함)
    verification/                  # UI 검증 이미지
    ...                            # 기존 실험 결과 그대로 보존
  workflow/local/<device_id>/       # 장비별 사용자 실행 코드, 기존 workflow ignore 적용
docs/configuration/                # Git 추적: 사용 설명
```

`config`에는 Python 코드를 두지 않는다. `configuration`을 import하는 것만으로 파일을 이동하지 않는다.
설정 예제나 기본값도 Git에서 배포하지 않으므로 새 clone에는 별도 로컬 설정 묶음이 필요하다.
장비 주소·제한·핀 매핑을 다른 PC 값으로 덮어쓰지 않는다. 앱은 최소 설정 묶음이 없으면 GUI/장비 코드를 불러오기 전에 복원 안내를 표시한다.
기존 실행 기록 속 설정 사본은 재현용 데이터이므로 `data`에 남긴다.
명시적으로 선택한 외부 저장 폴더는 유지하며, 기본 저장 위치는 위 경로를 사용한다.

## 다른 PC: 반드시 pull 전에 백업

GUI와 실행 중인 실험을 종료한다. 아래 작업은 **업데이트할 PC 자체**에서 한다.
이번 커밋은 과거에 추적하던 설정을 삭제하므로, 변경이 없는 로컬 설정도 pull 과정에서 사라질 수 있다.
`.gitignore`만으로 이미 추적 중인 파일이 보호되지는 않는다.

1. 저장소 **밖** 새 폴더에 현재 저장소 전체를 복사한다 (`.git`, 가상환경, 캐시는 제외 가능).
   반드시 `labremote/config`, `labremote/data`, 루트 `data`/`logs`, `labremote/phase_shifter/calibrations`,
   `docs/examples`, 사용자 workflow 및 루트 검증 이미지가 포함되어야 한다.
   추가로 `git diff --binary HEAD`, `git status --short`, `git rev-parse HEAD`를 파일로 보관한다.
   복사된 각 원본의 SHA256을 `Get-FileHash`로 비교해 백업을 검증한다.
   백업이 검증되지 않았으면 다음 단계로 넘어가지 않는다.
2. `git status --short`에서 코드 변경과 설정 변경을 구분한다. 코드 변경은 별도 로컬 커밋/브랜치에 보존한다.
   아직 추적 중인 설정 때문에 pull이 막히면, **백업을 확인한 설정 경로만**
   `git restore --source=HEAD --staged --worktree -- labremote/config`로 Git 버전으로 되돌린다.
   다른 경로의 로컬 수정도 각각 검토한다. 전체 `reset --hard`나 무조건적인 stash/pop은 사용하지 않는다.
3. 이 변경이 원격에 커밋·push된 뒤 업데이트한다. 예: `git pull --ff-only`.
   로컬 코드 커밋이 있어 fast-forward가 안 되면 해당 코드 변경을 merge/rebase로 보존한다.
4. 앱을 실행하기 전에 **이 PC의 백업**에서 설정과 데이터를 복원한다.
   `labremote/config`의 JSON/YAML/이미지 등 실제 설정은 동일한 상대 위치에 복원한다.
   예전 `config` 루트의 `*.py`, `__pycache__`, `ui/INPUT_DEFAULTS.md`는 복원하지 않는다.
   `config/devices/fpga/workflows.local`의 사용자 Python 코드는 `labremote/workflow/local`로 복원한다.
   data/logs/보정 파일/JSON·YAML 예제는 우선 옛 상대 경로로 복원해 아래 도구가 이전하게 한다.
   **복원 대상에 다른 내용의 파일이 있으면 덮어쓰지 말고 별도 보관 후 올바른 로컬 값을 선택한다.**
5. 저장소 루트에서 dry-run 후 명시적으로 이전한다. `python`은 GUI와 같은 Python 환경을 사용한다.

   ```powershell
   python -m labremote.configuration.local_storage
   python -m labremote.configuration.local_storage --apply --backup D:\RETempGUI-backups\migration-PC1-YYYYMMDD
   ```

   `--backup`은 저장소 밖의 아직 없는 새 디렉터리여야 한다. 이 도구는 이동 대상과 config를
   복사·해시 검증한 후 이동한다. 서로 다른 동명 파일은 전체 사전 검사에서 중단한다.
   DAC 폴더 등 **현재 저장소의 옛 절대 경로**와 `${PROJECT_ROOT}` 경로만 수정한다.
   다른 PC의 절대 경로나 임의 외부 폴더는 자동 추측하지 않으므로 필요하면 로컬 설정에서 직접 선택한다.
   아주 오래된 config 루트 파일은 `configuration.migration.migrate`에 남아 있는 명시적 이전 함수를
   검토한 뒤 별도 실행할 수 있다. import 시 자동 실행되지는 않는다.
6. `operations/micromotion/EA.two_rf.local.json`, `EC.two_rf.local.json`이 없는 PC는
   기존에 저장한 Two-RF 설정을 옮기거나 아래 값을 **새 파일에만** 작성한다.
   기존 설정 파일이 있으면 전압을 덮어쓰지 않는다.

   EA: `{"chamber":"EA","rf_unit":"Vpp","rf_low":0.16,"rf_high":0.9,"rf_final":0.9}`

   EC: `{"chamber":"EC","rf_unit":"Vpp","rf_low":0.1,"rf_high":0.19,"rf_final":0.19}`

   Two-RF의 Load/Save 기본 폴더는 이 설정 위치다. 과거 임의 이름으로 data에 저장한 설정은
   내용이 실행 결과의 동결 사본이 아닌지 확인하고 UI Load → Save로 이곳에 저장한다.
7. 아래 명령에서 첫 명령의 출력이 없어야 하고, 두 번째 명령은 ignore 규칙을 보여야 한다.

   ```powershell
   git ls-files -- labremote/config labremote/data logs data labremote/phase_shifter/calibrations
   git check-ignore labremote/config/ui/defaults.json labremote/data/calibration/phase_shifter/ramsey_data_20261110.json
   ```

   장비 연결 전에 해당 PC의 주소·핀 매핑·DAC preset·EA/EC RF 값을 확인한다.
   이후 설정/실험 로그 변화는 Git 변경 목록에 나타나지 않는다. 일반 코드 변경은 여전히 pull 전에 정리해야 한다.

## 이미 보존한 설정과의 충돌

이전 도구는 내용을 선택하거나 덮어쓰지 않는다. 충돌한 두 파일을 모두 백업한 후
사용할 버전을 명시적으로 고르고 다시 dry-run한다. migration 백업의 `manifest.json`과
`migration.json`에는 원본 해시와 이동 목록이 남는다. 데이터 본문은 변경하지 않는다.
업데이트가 실패해도 검증된 최초 백업은 제거하지 않는다.
