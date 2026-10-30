# GitHub와 분리한 로컬 장비 설정

실제 IP·모터 시리얼은 소스 코드에 입력하지 않습니다. 아래 로컬 파일은 `.gitignore`로 제외됩니다. 파일을 직접 전달할 때도 GitHub의 파일 업로드, Issue, PR, 공개 첨부에 넣지 마세요.

## 직접 옮길 파일

모든 경로는 저장소 루트 기준입니다.

| 파일 | 내용 | 복사 대상 |
|---|---|---|
| `labremote/config/local_hardware.json` | 메인 InstrumentServer와 모터 InstrumentServer의 host/port | UI를 실행할 PC의 동일한 상대 경로 |
| `server_deploy_latest/KDC101/serials.local.json` | 모터 이름별 실제 USB 시리얼 | 실제 모터 서버에 배포된 `KDC101.py`와 같은 폴더 |
| `local_settings.bat` | Conda 환경·설치 경로, 외부 InstrumentServer 소스 경로, 선택적 서버 override | UI PC 저장소 루트. 복사 후 해당 PC에 맞게 경로 확인 |
| `labremote/config/client_settings.json` | 저장된 UI 상태와 CCD 옵션(카메라 serial/DLL/저장 경로 포함 가능) | 기존 설정을 그대로 쓸 때만 UI PC의 동일 경로. 앱을 종료한 상태로 복사 |

이번 이전 작업은 첫 두 파일에 기존 IP·12개 모터 시리얼을 보존합니다. `local_settings.bat`도 기본 실행 설정으로 준비합니다. `client_settings.json`은 앱 사용 후 생성되는 선택 파일이므로 아직 없을 수 있습니다.

클라이언트 PC만 옮길 때는 `serials.local.json`을 클라이언트에 설치할 필요가 없습니다. 모터 서버 드라이버를 이번 버전으로 교체할 때 그 파일도 함께 배치해야 합니다. 기존 서버 설정에 `serial_number`를 직접 지정했다면 그 값이 우선하며, 해당 서버 설정 역시 로컬로 보관하세요.

## 읽기 우선순위와 기존 동작

- 메인 서버: loopback 기본값 → 저장된 `client_settings.json` → `local_hardware.json` → 명령행 `--host/--port`.
- 실행 배치 파일은 기본적으로 JSON을 사용합니다. `local_settings.bat`에 `SERVER_IP/SERVER_PORT`를 명시한 경우에만 명령행으로 덮어씁니다.
- 모터 서버: 기존 YAML과 장비별 설정을 합친 뒤 로컬 JSON의 `motor_host/motor_port`만 덮어씁니다. 이동 제한·단위·timeout·장비 이름은 기존 YAML을 그대로 사용합니다.
- 모터 시리얼: 명시적인 서버 init `serial_number` → 드라이버 옆 `serials.local.json`. 파일은 드라이버 import 시 읽으므로 변경 후 서버를 재시작하세요.
- 로컬 파일이 없는 새 clone은 IP가 loopback으로 표시됩니다. 모터 시리얼은 추정하지 않으며 실제 번호 없이 장비를 등록하면 오류가 납니다. JSON 형식 오류도 명확하게 실패합니다.
- UI 모양, workflow, CCD 처리, 모터 이동과 USB 동작은 변경하지 않습니다.

새 환경을 수동 설정하려면 Git에 포함된 `local_hardware.example.json`을 사용하세요. 모터용 `serials.example.json`은 Git에서 제외된 로컬 `server_deploy_latest/KDC101/`에 있으며, 서버 드라이버 폴더를 직접 전달받아 사용합니다. 각각 해당 로컬 파일 이름으로 복사한 뒤 값을 입력하세요. 예제 파일에는 실제 값을 넣지 마세요.

## 업로드 전 확인

저장소 루트에서 `python check_public_files.py`를 실행하면 추적 파일과 Git에 추가될 새 파일에서 내부 IP, 로컬 설정값, 토큰 패턴, 이메일을 검사합니다. 민감한 값 대신 위치와 종류만 출력합니다. GitHub Desktop의 Changes에도 위 로컬 파일이 나타나지 않아야 합니다.

이 검사는 수동 실행이며 모든 개인정보를 탐지하거나 강제 업로드를 막는 보안 장치는 아닙니다. 이미 추적된 파일은 `.gitignore`만으로 추적이 해제되지 않습니다. 외부 코드 작성자·저작권 표기는 출처 보존을 위해 유지합니다.

## 이미 올라간 기록과 이메일

이번 수정은 현재 파일을 정리합니다. 이전 커밋의 IP·시리얼·작성자 이메일은 그대로 남으므로 새 commit/push만으로 과거 정보가 삭제되지 않습니다.

앞으로의 이메일은 GitHub Settings → Emails에서 비공개 이메일 옵션을 켜고, 거기에 표시되는 정확한 `noreply` 주소를 GitHub Desktop File → Options → Git의 Email에 설정하세요. 저장소별 설정이 있으면 Repository → Repository settings → Git config도 확인합니다. 작성자 이름도 공개되는 이름으로 설정해야 합니다.

이미 게시된 기록을 제거하는 선택지는 다음과 같습니다.

1. 기존 기록 유지: 별도 새 clone에서 `git-filter-repo` 등으로 과거 파일 내용과 author/committer 이메일을 모두 정리한 후 원격 기록을 교체하고 다른 PC는 다시 clone합니다. 이는 커밋 해시와 협업 기록에 영향을 주므로 별도 작업으로 진행합니다.
2. 초기 저장소라 기록이 필요 없음: 정리된 현재 파일로 새 저장소를 만들고 noreply 이메일로 첫 커밋을 생성합니다. 기존 `.git`은 복사하지 않습니다. 위 로컬 파일은 Git에서 제외한 상태로 보존하고, 이전 저장소의 공개 상태·보관·삭제 여부는 별도로 결정합니다.

어느 방법도 타인이 이미 받은 clone/fork 등의 사본까지 자동으로 지우지는 못합니다. 이번 작업에서는 force push, Git 기록 재작성, 저장소 삭제를 실행하지 않습니다.

참고: [GitHub Desktop Git 설정](https://docs.github.com/en/desktop/configuring-and-customizing-github-desktop/configuring-git-for-github-desktop), [커밋 이메일 설정](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address), [민감한 기록 제거](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

## 로컬 전용 지원 폴더

`tests/`와 `server_deploy_latest/`는 기존 경로를 유지하되 Git에서 제외됩니다. 새 clone에는 두 폴더가 없으며 UI 실행에는 필요하지 않습니다. 회귀 테스트가 필요하면 코드 버전에 맞는 두 폴더를 함께 직접 복사하세요. 모터 서버를 새로 구성한다면 로컬 `server_deploy_latest/KDC101/` 드라이버와 `serials.local.json`을 직접 전달합니다.

현재 PC에서는 추적만 해제하고 실제 파일은 보존합니다. 기존 다른 clone에서 추적 해제 커밋을 pull하면 이전에 추적하던 파일이 삭제될 수 있으므로 필요한 파일을 먼저 백업하세요. GitHub의 과거 커밋에서도 제거하려면 별도의 새 기록 생성/기록 정리가 필요합니다.
