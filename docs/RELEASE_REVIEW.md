# RETempUI V1.00 릴리스 검토

검토일: 2026-10-30. 현재 v7 기능을 기준으로 GitHub 저장소 루트에 바로 사용할 수 있는 단일 폴더로 정리했습니다. Git 초기화·commit·push·서버 배포는 수행하지 않았습니다.

## 확인 결과

| 항목 | 결과 |
|---|---|
| 단위·통합 회귀 테스트 | 21개 모듈, 총 283개 테스트 통과 |
| CCD GUI | 1392×1040 Dummy 영상, 이온 조건 만족, 숨긴 탭에서도 조건 대기 통과 |
| CCD 마우스/배치 | 왼쪽 영상·오른쪽 제어, 휠 확대, 가운데 버튼 사각형 확대, 라이브 확대 유지 통과 |
| 앱 종료 | CCD를 포함한 모든 worker 정상 종료 확인 |
| Python 소스/설정 | 장비·테스트·서버 참고본 254개 Python 파일 구문 검사, 장비 YAML/registry 검사 통과 |
| 문서 링크 | README 및 docs 내부 링크 확인 |
| 의존성 | 통합 requirements와 검증 버전 제약에 대해 설치 없이 dry-run 검사 통과 |
| 실제 장비 | 연결·조작하지 않음. 실제 CCD/SDK latency 및 장비 출력은 미검증 |

테스트는 모듈별 독립 프로세스로 실행했습니다. 초기 실행에서 실패한 2개 모듈은 아래 조치 후 재실행하여 통과했으며, 나머지 모듈 결과와 합산한 수가 283개입니다. 원본 로그는 배포본에서 제외하고 기존 작업 디렉터리의 보관 자료에 남깁니다. 필요하면 `python verify_release.py --suite all`로 재생성할 수 있습니다.

## 검토 중 반영한 사항

1. 기존 FPGA 성공 측정 테스트가 추가 cleanup 업로드를 기대하고 있었습니다. 현재 성공 경로는 노출 프로그램 자체가 counter disable/STOP을 수행하므로 추가 업로드가 없습니다. 테스트를 성공 경로 1회 업로드, 별도 stop 호출 없음으로 수정했습니다. 실패/취소 cleanup 검증은 유지했으며 실제 FPGA 제어 코드는 변경하지 않았습니다.
2. PID/XYZ 모듈은 GUI/스캔 검증을 합쳐 약 87초가 걸려 초기 75초 제한에 걸렸습니다. 충분한 제한 시간으로 32개 테스트가 통과했습니다. 검증 스크립트 기본 모듈 제한은 180초입니다.
3. 이전 전체 실행에서 관찰된 FPGA Input counts 테스트 실패는 독립 프로세스 재검증에서 재현되지 않았고 12개 관련 테스트가 통과했습니다.
4. 누락된 Pillow 및 별도 InstrumentServer 클라이언트의 Python 의존성을 설치 목록에 추가했습니다. 실제 검증 환경의 직접 의존성 버전을 `constraints-tested.txt`에 기록했습니다.
5. PC별 Conda/서버/외부 소스 경로를 `local_settings.bat`에서 덮어쓸 수 있도록 했습니다. 이 파일과 앱의 `labremote/config/ui/client_settings.local.json`은 Git에서 제외됩니다.
6. 서버 드라이버 안내의 오래된 Motor Server 문구를 실제 QCoDeS/InstrumentServer 구성에 맞게 고쳤습니다. 사용하지 않는 KDC101 legacy Windows 드라이버와 실험실 개별 config.yaml은 배포본에서 제외하고 서버 설정 예제는 유지했습니다.

## 유지 및 제외 기준

유지: 앱 진입점, 실행 배치 파일, 공통 API/runtime, 모든 현재 장비 구현, UI SVG 자산, 장비 정책 YAML 24개, workflow 예제, 테스트 소스, 호환 서버 드라이버 참고본, 설치 목록, 사용 문서.

제외: 로그/측정 결과, 테스트 임시 폴더, 생성된 스크린샷/CSV/NPZ, pycache/pyc, 이전 버전 복사본/ZIP, 과거 배포 스크립트, PC별 저장 설정, 미사용 legacy 드라이버. 필요한 설정의 `.example` 파일은 포함합니다.

`release_manifest.json`은 전달 파일들의 상대 경로·크기·SHA-256을 기록합니다. manifest 자체는 자기 해시 목록에서 제외합니다. 검증 후 코드를 수정하면 manifest는 이전 배포 시점의 기록으로 취급하세요.

## 실기 적용 시 남는 확인

- 실제 PC에 호환 InstrumentServer 소스와 ThorCam SDK/드라이버가 있어야 합니다. 이 저장소는 제조사 DLL과 InstrumentServer 전체를 포함하지 않습니다.
- 카메라 serial/DLL 경로, 장비 서버 주소, FPGA COM 및 모터 서버 설정은 환경에 맞게 지정해야 합니다.
- 실제 CCD 영상 방향, bit depth, threshold, 노출과 연속 촬영/중단, 물리적 latency는 현장에서 확인해야 합니다.
- CCD는 flip mirror·오븐·셔터 없이 동작합니다. 이 최초 검토 이후 EC 오븐 자동 가동/종료 operation이 추가되었습니다. 현재 범위는 [오븐 로딩 안내](OVEN_LOADING_KO.md)를 참고하세요.
- 자동 테스트 통과는 실제 장비 전체의 무오류 동작 보증을 뜻하지 않습니다.

> 이후 배포 정책 변경: `tests/`와 `server_deploy_latest/`는 로컬에만 보존하며 Git에서 제외합니다. 위 테스트 결과는 당시 로컬 지원 폴더를 포함한 검증 기록입니다. 새 clone에서의 검증 범위는 현재 README를 따릅니다.
