# RETempUI V1.00

실험 장비 제어용 Windows/PyQt5 클라이언트입니다. 기존 v6의 장비 UI와 공통 workflow 실행 구조에 **로컬 CCD, 이온 검출 조건 대기, 대용량 영상 표시**를 추가한 v7을 GitHub 작업용으로 정리했습니다.

## 주요 기능

| 화면 | 기능 |
|---|---|
| 메인 탭 | 전체 장비 구성 파일, 그룹 연결, 상세 창 열기 |
| Monitor 탭 | 추후 구성용 빈 화면 |
| RF 상세 창 | Windfreak, SG384, AnaPico, DDS 설정·조회·출력 제어 |
| 오실로스코프 상세 창 | DS1052E/MSO7054 파형과 측정값 조회 |
| 미라 상세 창 | THERMOTEK, OSA, MDT 및 PID 연동 |
| 기타 상세 창 | Keithley, 모터, flipper / 셔터 |
| FPGA 상세 창 | FPGA 출력·광자수 측정, XY/XYZ 스캔 |
| CCD 상세 창 | 로컬 ThorCam/Dummy, 연속·N장 촬영, uint16 TIFF/PNG 저장, ROI 이온 검출 |
| CCD → EC oven | 171/174 선택, CH1 전류·전압 표시, 릴레이·EC 셔터 연동, 이온 조건 또는 10분 timeout 후 OFF |
| Workflow 탭 | `main(devices)` Python 파일을 실행하고 공통 핸들로 완료·실패·취소 처리 |

장비별 세부 동작은 [장비 가이드](docs/DEVICE_GUIDE_KO.md), CCD와 조건 판정은 [CCD 가이드](docs/CCD_GUIDE_KO.md)를 참고하세요.

EC 오븐은 [오븐 로딩 안내](docs/OVEN_LOADING_KO.md)를 참고하세요. 기본 서버 등록 이름은 `oven_psu` / `oven_relays`, 출력은 CH1입니다. EC 171은 5.000 V / 1.30 A, EC 174는 5.000 V / 1.40 A이며 기본 EC 셔터는 `shutter_2`이며 별도 확인 체크박스 없이 시작합니다. Flipper 자동 경로는 로컬 매핑을 명시적으로 활성화한 경우에만 적용합니다. 자동 종료는 정상 동작 중인 클라이언트와 통신에 의존하며 하드웨어 watchdog을 대신하지 않습니다.

## 설치 및 실행

검증 기준은 **Windows 64bit, Python 3.11, Conda `uniqcon` 환경**입니다.

### 1. Python 환경

기존 `uniqcon` 환경이 있으면 생성 명령을 생략합니다. Anaconda Prompt에서:

```bat
conda create -n uniqcon python=3.11
conda activate uniqcon
cd /d D:\coding\QCODES\RETempUI_V1_00
python -m pip install -r requirements.txt
```

`requirements.txt`는 기본 UI와 CCD, 실험실 InstrumentServer 클라이언트의 Python 의존성을 함께 설치합니다. [constraints-tested.txt](constraints-tested.txt)로 검증한 직접 의존성 버전을 지정합니다(모든 하위 의존성의 완전한 lock 파일은 아닙니다). `cv2` 오류는 `opencv-python-headless`가 실행 환경에 설치되지 않았을 때 발생합니다. `pip`만 호출하기보다 해당 환경의 `python -m pip`를 사용하세요.

```bat
python -c "import PyQt5, yaml, numpy, matplotlib, zmq, serial, scipy, PIL, cv2, pyqtgraph, clr; print('Client dependencies OK')"
```

### 2. InstrumentServer 클라이언트

원격 장비에는 실험실에서 사용 중인 **호환 InstrumentServer 소스/환경**이 추가로 필요합니다. 이 저장소에 InstrumentServer 전체를 복제하지 않았습니다. 로컬 CCD의 Dummy 실행에는 원격 서버가 필요하지 않습니다.

배치 파일은 주변 폴더의 다음 구조를 자동 탐색합니다.

```text
D:\coding\QCODES\
├─ RETempUI_V1_00\
└─ instrumentserver-remote_entanglement\
   └─ instrumentserver-remote_entanglement\
      ├─ setup.py
      └─ instrumentserver\
```

다른 위치에 있으면 `local_settings.bat`의 `IS_ROOT`를 **instrumentserver 패키지를 포함하는 폴더**로 지정하세요. 위의 통합 의존성을 설치한 뒤, 실험실 소스를 editable 설치할 수도 있습니다.

```bat
python -m pip install -e "D:\path\to\instrumentserver-source"
python -c "from instrumentserver.client import Client; print('Remote client import OK')"
```

위 경로는 실제 소스 폴더로 바꾸세요. 배치 파일 자동 탐색/PYTHONPATH만 사용하는 경우에는 editable 설치를 생략할 수 있습니다. 별도 fork에서 의존성이 추가되었다면 해당 환경에도 설치해야 합니다.

### 3. PC별 실행 설정

먼저 [로컬 설정 전달 안내](docs/LOCAL_SETUP_KO.md)에 따라 `labremote/config/devices/connections.local.json`을 직접 복사하세요. 실제 IP와 모터 시리얼은 GitHub에 포함하지 않습니다. 새 checkout에는 loopback 기본값만 있으며 실제 연결에는 로컬 설정이 필요합니다.

```bat
copy local_settings.example.bat local_settings.bat
```

`local_settings.bat`에서 다음을 확인합니다. 이 파일은 Git에서 제외되므로 다른 컴퓨터에서 `pull`해도 PC별 설정이 유지됩니다.

- `CONDA_BAT`: Conda 활성화 스크립트 경로. 기본값 `C:\Anaconda\condabin\conda.bat`
- `CONDA_ENV`: 실행 환경. 기본값 `uniqcon`
- `SERVER_IP`, `SERVER_PORT`: 선택적 명령행 덮어쓰기. 기본 네트워크 설정은 `labremote/config/devices/connections.local.json` 사용
- `IS_ROOT`: 선택 사항. 별도 InstrumentServer 소스 경로

실행:

```bat
start_lab_remote_gui.bat
```

이미 환경이 활성화되어 있다면 `python lab_remote_gui.py --host 서버주소 --port 5555`로도 실행할 수 있습니다. 이 경우 배치 파일의 경로 자동 탐색과 `local_settings.bat` 적용은 수행되지 않습니다.

### 4. 실제 CCD

- ThorCam 프로그램, 카메라 드라이버, Thorlabs .NET SDK를 해당 PC에 설치합니다. 이 저장소에 제조사 DLL을 포함하지 않았습니다.
- CCD 탭에서는 `Thorcam`을 선택합니다. 카메라 serial과 DLL 입력칸은 표시하지 않으며, 필요한 경우 로컬 `labremote/config/ui/client_settings.local.json`의 `ccd_options.serial`과 `ccd_options.dll_path`로 지정합니다. 기본 경로는 `C:/Program Files/Thorlabs/Scientific Imaging/ThorCam/`입니다.
- `Dummy`는 SDK/실제 카메라 없이 밝은 영역 3개를 생성합니다.
- CCD는 로컬로 연결되며 **flip mirror·오븐·셔터가 없어도 동작**합니다. 일반 CCD Wait for ions는 장비를 끄지 않습니다. EC oven 로딩 작업을 시작한 경우에만 해당 작업이 PSU OFF와 셔터 닫기를 처리합니다.
- 단색 16bit 영상이 대상입니다. EMCCD·컬러 카메라·하드웨어 TTL 트리거는 현재 통합 범위가 아닙니다.

## CCD 화면 조작

왼쪽은 이미지, 오른쪽은 연결·촬영·검출·표시·저장 설정입니다. 가운데 구분선으로 폭을 조절하며 오른쪽은 독립 스크롤됩니다.

| 마우스 조작 | 동작 |
|---|---|
| 휠 스크롤 | 마우스 위치 기준 확대/축소 |
| 휠 버튼을 누른 채 드래그 | 선택한 사각 영역 확대 |
| 왼쪽 버튼 드래그 | 이미지 이동 |
| Display → Fit image | 전체 영상으로 복귀 |

촬영 중에도 확대 영역을 유지합니다. 화면 확대/반전은 분석 ROI와 원본 저장 값을 바꾸지 않습니다.

## 이온 검출과 workflow

원래 CCD 코드의 threshold + 외부 contour + 최소 면적 방식을 유지합니다. 검출 개수는 밝은 연결 영역 수이며, 목표 조건은 **`count >= target`**입니다.

카메라 프로세스에서 검출하므로 다른 탭을 보거나 창을 최소화해도 조건 대기가 계속됩니다. 화면에는 최신 프레임만 공유 메모리로 전달하고, 명령/완료 메시지만 Pipe로 전달합니다. UI 표시를 위해 모든 프레임을 큐에 쌓지 않습니다.

먼저 CCD 탭에서 연결한 뒤 workflow에서 실행합니다.

```python
def main(devices):
    ccd = devices.ccd('ccd_local')
    ccd.configure_detection(threshold=1000, min_area=3, target=3).wait()
    ccd.start_acquisition().wait()
    try:
        result = ccd.wait_for_ions(
            target=3, consecutive_frames=3, timeout_s=60
        ).wait()
        print('조건 만족:', result['count'])
        # 다음 실험 단계를 여기에 추가
    finally:
        ccd.stop_acquisition().wait()
```

새 프레임부터 연속 조건을 판단하며 timeout·취소·연결 오류를 구분합니다. 위 일반 CCD 대기 예제는 다른 장비를 제어하지 않습니다. EC 오븐의 자동 가동·종료에는 별도 `devices.ccd().load_oven(...)` 또는 CCD 화면의 Oven ON을 사용하세요. Flip mirror 자동 연동은 포함하지 않습니다.

예제: [조건 대기](labremote/workflow/ccd_wait_for_ions.py), [조건이 만족될 때까지 반복](labremote/workflow/ccd_repeat_until_ions.py).

## GitHub 작업과 실제 PC 반영

이 폴더를 저장소 루트로 사용합니다. 코드 변경 → 검증 → 직접 commit/push → 실제 PC에서 앱을 종료하고 pull → 필요시 의존성 재설치 → 앱 재시작 순서로 사용하세요. 이번 정리 작업에서는 Git 초기화·remote 설정·commit·push를 수행하지 않았습니다.

실제 PC에서 이미 저장소를 연결한 뒤 업데이트할 때:

```bat
git status
git pull --ff-only
conda activate uniqcon
python -m pip install -r requirements.txt
start_lab_remote_gui.bat
```

수정된 추적 파일이 있다면 먼저 commit 또는 stash로 보존한 후 pull하세요. `labremote/config/devices/*/*.yml` 및 `labremote/config/operations/*/*.yml`은 장비 이름·단위·출력 제한을 포함하는 **공유 설정**으로 추적합니다. 환경별 변경이 필요하면 이 파일의 변경도 함께 관리해야 합니다.

`labremote/config/ui/client_settings.local.json`은 앱 종료 시 생성되는 PC별 UI 설정이며 Git에서 제외합니다. 공개 기본값은 `labremote/config/ui/defaults.json`에서 읽습니다. 새 checkout에서도 장비 기본 목록은 각 장비의 YAML 설정에서 불러옵니다.

## 폴더 구조

```text
RETempUI_V1_00/
├─ README.MD
├─ lab_remote_gui.py                # 앱 진입점
├─ start_lab_remote_gui.bat         # Conda/서버 경로를 적용하는 실행 파일
├─ local_settings.example.bat       # PC별 설정 예제
├─ requirements*.txt                # 설치 의존성
├─ labremote/
│  ├─ api/                         # UI/workflow 공통 API
│  ├─ devices/                     # 장비 worker 및 로컬 CCD/FPGA
│  ├─ operation/                   # 장비별 동작
│  ├─ runtime/                     # 큐·취소·기록·workflow 실행
│  ├─ config/                      # 장비 설정·검증 규칙
│  ├─ ui/                          # 기존 장비 화면
│  └─ workflow/                    # 실행 가능한 workflow 예제
├─ tests/                          # 로컬 전용 회귀 테스트 (Git 제외)
├─ server_deploy_latest/           # 로컬 전용 서버 드라이버 (Git 제외)
├─ docs/                           # 장비·CCD·검토 문서
├─ verify_release.py               # 패키지 검증 및 격리 테스트 실행
└─ verify_ccd_v7.py                # 더미 CCD GUI/마우스/종료 검증
```

위 구조는 개발 PC 기준입니다. `tests/`와 `server_deploy_latest/`는 기존 위치에 보존하지만 Git에서 제외하므로 새 clone에는 없습니다. UI 실행에는 필요하지 않습니다. 서버 드라이버나 회귀 테스트가 필요한 PC에만 두 폴더를 직접 전달하세요. 서버 드라이버는 자동 배포하지 않으며 로컬 폴더의 `server_deploy_latest/README.md`를 참고합니다.

## 검증

실제 하드웨어 없이 실행하는 검사입니다. 새 clone에서도 기본 검사와 Dummy CCD GUI 검사를 실행할 수 있습니다:

```bat
python verify_release.py
python verify_release.py --suite ccd-gui
python check_public_files.py
```

`verify_release.py`의 기본값은 `--suite checks`입니다. 소스 구문·장비 설정·문서 링크를 검사하며, 로컬 두 폴더가 있으면 해당 Python 소스도 검사합니다.

`tests/`와 `server_deploy_latest/`를 별도로 복사한 개발 PC에서는 다음 회귀 테스트도 사용할 수 있습니다:

```bat
python verify_release.py --suite core
python verify_release.py --suite all
```

필요한 로컬 폴더가 없으면 회귀 테스트는 안내와 함께 실패 종료합니다. 테스트 0개를 성공으로 보고하지 않습니다. 두 폴더는 Git으로 업데이트되지 않으므로 사용하는 UI 코드 버전에 맞춰 함께 보관하세요.

검증기는 주변 InstrumentServer 소스를 자동 탐색하며, 테스트 모듈을 독립 프로세스로 실행합니다. 결과는 Git에서 제외되는 `.verification/`에 기록합니다. 상세 검토 결과와 미검증 사항은 [릴리스 검토](docs/RELEASE_REVIEW.md)에 정리합니다.

실제 CCD 노출/USB/SDK/모니터 표시 지연은 더미 검증으로 보장할 수 없습니다. 실기 연결과 영상 방향·검출 threshold·촬영/정지 동작을 확인한 뒤 실험에 적용하세요.

## 제외한 자료

이전 v3/v4/v5/v6/v7 복사본, ZIP, 로그, 측정 데이터, 테스트 임시 디렉터리, 생성된 PNG/NPZ/CSV, `__pycache__`, `.pyc`, PC별 저장 설정을 배포본에서 제외했습니다. 재생성되는 파일은 `.gitignore`로 제외합니다. 원본과 과거 작업 자료는 기존 작업 디렉터리의 별도 보관 폴더에 남깁니다.

두 폴더를 이미 추적하던 저장소에서는 이번 변경이 GitHub Desktop에 삭제 항목으로 표시됩니다. 이는 Git 추적 해제이며 이 PC의 실제 파일은 남아 있습니다. 기존 다른 checkout에서 이 변경을 pull하면 그곳의 추적 파일은 삭제될 수 있으므로, 필요한 서버 드라이버·테스트는 먼저 별도 백업하세요. 과거 커밋의 파일은 별도 기록 정리 전까지 남습니다.

## MFF101 flipper와 EC 셔터

Flipper는 메인 창 상단 QCoDeS InstrumentServer 주소를 공유합니다.
상단 `Rescan server devices` 또는 `others → flip`의 `서버 flipper 목록 불러오기`로 실제 서버 이름을 조회하고,
각 장비의 연결·Position 1/2 버튼으로 제어하거나 `Flipper 전체 연결`을 사용합니다.
EA/EC 경로 버튼은 제거했으며 기존 `labremote/config/operations/flipper_routes.local.json` 자동 매핑은 유지합니다.
메인 상단 `장비` 메뉴와 창 동작, CCD 수신 범위는 [장비 창 안내](docs/FLIP_WINDOWS_KO.md)를 참고하세요.

기존 oven_relays.shutter_2를 함께 제어합니다. Linux 서버 드라이버/YAML,
USB 포트 확인, EA/EC 매핑 설정은 [설치 안내](docs/FLIP_SETUP_KO.md)를 참고하세요.
자동 광로 전환은 기본 OFF이며 실제 매핑을 지정한 후 활성화합니다.

## CCD 포획과 FPGA 시퀀서 파일 workflow

이온 1개 이상 검출 시 오븐을 종료하는 예제와 UI PC의 시퀀서 파일을 실행하는
`devices.fpga().run_sequence_file(...)` API를 제공합니다.
[사용법과 예제 파일](docs/WORKFLOW_CCD_FPGA_KO.md)을 참고하세요.


### Scan / scope / CCD display updates

- Fixed scan tabs: Scan EA collection (`EA_px/py/pz`), Scan EA excitation (`EA_sx/sy/sz`), Scan EC collection (`EC_px/py/pz`), Scan EC excitation (`EC_sx/sy/sz`). Existing default PMT associations are preserved (0, 3, 1, 2 in this tab order).
- Current motor positions are displayed in micrometres. Conversion factors remain in `scan_defaults`; the conversion editors have been removed from the UI. Idle visible tabs read status through the operation queue; active scans reuse move readbacks. `(last)` marks a readback older than three seconds.
- `Load last scan settings` restores ranges, steps, exposure, average, settle time, PMT, Z-scan enable and save directory from the last scan started in that tab. Settings are stored in ignored `labremote/config/ui/scan_EA_px.local.json`, `scan_EA_sx.local.json`, `scan_EC_px.local.json`, and `scan_EC_sx.local.json`. Copy these privately only if you want to transfer previous settings.
- `Move Z` moves to an absolute Z target without enabling Z scan or connecting the FPGA. The Z motor must be connected and free of active workflows.
- XYZ scans show MFD X and MFD Y versus Z below the image, updated after each completed XY plane. Failed or unavailable fits are gaps, not zero-width measurements. Individual Start/Stop controls remain; the FPGA-wide Start/Stop all scan buttons were removed.
- DS1052E/MSO7054 waveform refresh reuses axes and line objects, while preserving physical V/div, fit-to-data and manual-limit modes.
- CCD zoom-out is limited to the full sensor view, with padding only as needed to preserve square pixels at the viewport aspect ratio. Fit image restores this view; live frames retain zoom.


## 실험 중심 메인 화면과 Configuration

메인은 `메인 / Workflow / Monitor`로 구성됩니다. RF·미라·CCD·FPGA·오실로스코프·기타
상세 제어는 버튼으로 별도 창을 엽니다. 창을 닫아도 연결·촬영·작업은 유지됩니다.
Workflow API와 장비별 설정, operation 실행 방식은 기존 그대로입니다.

`Configuration`에서 전체 장비 구성을 불러오고 표에서 편집한 뒤 저장할 수 있습니다.
`labremote/config/ui/equipment.local.json`의 사용 체크는 그룹/전체 연결 대상을 지정합니다.
개인 파일은 Git에서 제외되며, 공개 형식은 [equipment.json](labremote/config/ui/equipment.json)입니다.
수동으로 연결한 장비는 기존처럼 workflow에서 사용할 수 있습니다.
자세한 사용법과 연결/종료 동작은 [실험 UI 안내](docs/EXPERIMENT_UI_KO.md)를 참고하세요.

### CCD / FPGA 화면 업데이트

FPGA 포트 검색·기억, 화면 영역 기반 CCD 연속 검출, Configuration의 CCD Display 설정은 [CCD/FPGA 제어 안내](docs/CCD_CONTROLS_KO.md)를 참고하세요. 오븐은 별도로 켜며 포획 시 자동 종료와 기존 600초 제한을 유지합니다.

## 설정 파일 역할 분리

[설정 구조 및 이전 안내](docs/CONFIGURATION.md)를 참고하세요. 공개 기본값과 PC별 `*.local.json`을 구분하고, 장비 / 메인 UI / operation 설정을 각 폴더에서 관리합니다. 메인의 중복 상세 제어창 버튼은 제거했으며 상단 **장비** 메뉴에서 기존 상세 창을 엽니다.

CCD 밝기 조절과 flipper 위치 별명·이미지는 [표시 설정 안내](docs/FLIP_DISPLAY_KO.md)를 참고하세요.
