# RETempUI 로컬 CCD와 이온 조건 workflow

v6 복사본에 CCD 탭을 추가했습니다. 기존 RF/oscillo/mira/others/workflow 화면 및 서버 장비 구현은 유지합니다. CCD 영상과 제어는 로컬 프로세스에서 처리하며 InstrumentServer를 사용하지 않습니다. 앱 시작만으로 카메라에 연결하지 않습니다.

## 실행

`start_lab_remote_gui.bat` 실행 → CCD 탭 → Thorcam 또는 Dummy 선택 → Connect local CCD.

- Dummy는 밝은 영역 3개를 생성합니다. 실제 장비 없이 workflow를 확인할 수 있습니다.
- Thorcam은 첨부 CCD.zip의 .NET SDK 래퍼를 사용합니다. ThorCam/Thorlabs SDK가 별도로 설치되어 있어야 합니다. 기본 DLL 디렉터리는 `C:/Program Files/Thorlabs/Scientific Imaging/ThorCam/`입니다. 화면 입력칸은 제거했으며 별도 경로가 필요하면 로컬 labremote/config/ui/client_settings.local.json의 ccd_options.dll_path로 지정합니다.
- 여러 카메라가 연결되어 있으면 로컬 labremote/config/ui/client_settings.local.json의 ccd_options.serial을 지정해야 합니다. 단색 16bit 영상만 지원하며 컬러 카메라는 명시적으로 거부합니다.
- 추가 Python 패키지는 `requirements_ccd.txt`에 기록했습니다. SDK와 카메라 실물은 더미 검증에 사용하지 않았습니다.

## 유지한 기능과 변경한 표현

CCD 화면은 왼쪽 영상과 오른쪽 제어 패널로 나뉩니다. 가운데 구분선을 드래그하면 폭을 조절할 수 있고, 오른쪽 패널은 독립적으로 스크롤됩니다.

- 영상 위에서 휠 스크롤: 마우스 위치를 기준으로 확대/축소.
- 휠 버튼(가운데 버튼)을 누른 채 드래그: 사각형으로 선택한 영역 확대.
- 왼쪽 버튼 드래그: 영상 이동.
- 오른쪽 Display 그룹의 Fit image: 전체 영상으로 복귀.

확대는 화면 표시만 변경하며 검출 ROI를 바꾸지 않습니다. 라이브 영상이 갱신되어도 사용자가 지정한 확대 영역이 유지됩니다.

노출/gain 설정, 연속 촬영, 단일/N장 촬영, 촬영 완료 후 자동 TIFF 저장, TIFF/PNG 수동 저장, ROI 분석/저장, 확대/이동, 밝기 자동/수동 범위, 컬러맵, 좌우/상하 표시 반전, 픽셀 값 확인, 이온 검출을 제공합니다. 설정 변경 결과는 실제 카메라 readback을 사용합니다. 노출/gain 변경 전 촬영을 정지합니다.

- 이온 검출은 원본처럼 `pixel > threshold`, 외부 contour, 최소 contour 면적(기본 3)을 사용합니다. 밝은 연결 영역 개수이며 실제 이온 수를 별도로 학습한 모델은 아닙니다.
- 윤곽선 객체를 매 프레임 생성하는 대신 검출 중심에 재사용 가능한 빨간 마커를 표시합니다. 표시 마커는 최대 1024개지만 검출 개수에는 제한을 두지 않습니다.
- 좌표는 카메라에서 반환한 영상의 좌상단 원점, x=열, y=행입니다. 표시 반전은 검출 좌표나 저장 데이터에 영향을 주지 않습니다. SDK의 ROI/비닝이 설정되어 있다면 반환 영상 기준 좌표입니다. 예전 전치/상하 반전 표시와 방향이 다를 수 있으므로 첫 실기 연결에서 방향을 확인하세요.
- ROI는 소프트웨어 분석/저장 ROI입니다. 센서 전송량을 줄이는 하드웨어 ROI 설정은 추가하지 않았습니다.
- TIFF와 PNG는 원본 uint16 값을 보존합니다. 예전 PNG 자동 정규화와 int16 변환은 사용하지 않습니다. 화면 밝기 설정도 원본 저장 값에 영향을 주지 않습니다.
- 유한 촬영은 N장의 수신 완료로 끝납니다. Auto-save를 켜면 저장 완료까지 capture 핸들이 완료되지 않습니다. 라이브 모드 수동 sequence 저장은 현재 버퍼의 스냅샷입니다.
- 저장 파일은 덮어쓰지 않습니다. PNG는 1장, 여러 장은 TIFF를 사용합니다.

## workflow

먼저 CCD 탭에서 연결해야 `devices.ccd('ccd_local')`에 등록됩니다. UI와 workflow는 같은 카메라 프로세스와 명령 경로를 사용합니다. `.wait()`는 workflow 스레드에서 사용하고 UI에서는 완료 신호를 사용합니다.

```python
def main(devices):
    ccd = devices.ccd()
    ccd.configure_detection(threshold=1000, min_area=3, target=3,
                            roi=None).wait()
    ccd.start_acquisition().wait()
    try:
        result = ccd.wait_for_ions(target=3, consecutive_frames=3,
                                   timeout_s=60).wait()
        # 여기부터 다음 실험 단계
        print(result['count'], result['matched'])
    finally:
        ccd.stop_acquisition().wait()
```

예제 파일:

- `labremote/workflow/ccd_wait_for_ions.py`: true를 기다린 다음 단계 진행.
- `labremote/workflow/ccd_repeat_until_ions.py`: 조건 대기 중 실험 단계를 반복하는 위치 제공.

`wait_for_ions`는 카메라 프로세스에서 새로 분석한 프레임으로만 조건을 평가합니다. 요청 전에 SDK 큐에 있던 프레임과 요청 직후 노출 구간은 제외합니다. 프레임 번호가 건너뛰면 연속 검출 횟수를 초기화합니다. 정확한 광학 노출 시각과의 동기화는 실기 SDK 타임스탬프 검증이 추가로 필요합니다.

반환값에는 `count`, `matched`, `frame_id`, `device_frame_id`, `run_id`, `received_ns`, `analyzed_ns`, `detection_revision`, `consecutive_frames`가 포함됩니다. 조건은 `count >= target`입니다. GUI를 숨기거나 다른 탭으로 이동해도 분석과 조건 대기가 계속됩니다.

timeout은 `TimeoutError`, 사용자 중단은 `OperationCancelled`, 프로세스/카메라 오류는 예외로 전달합니다. false와 오류를 같은 값으로 처리하지 않습니다. 활성 조건 대기 중 threshold/ROI 변경은 거부하여 판정 기준이 섞이지 않게 합니다. 변경하려면 기존 대기를 취소하고 새 조건 대기를 시작합니다.

`start_acquisition()` 핸들은 시작 완료를 나타냅니다. workflow 종료만으로 라이브 촬영이 자동 종료되지는 않으므로 `finally: stop_acquisition().wait()`를 사용합니다. stop API는 workflow 취소 후에도 정리할 수 있습니다. 이온 조건 true가 다른 장비를 자동 정지시키지는 않습니다. 해당 장비의 정지 명령을 다음 단계 또는 finally에 명시하세요. 진행 중인 장비 명령의 중단 가능성은 각 장비 API를 따릅니다.

기타 API:

```python
ccd.configure(exposure_ms=30, gain=0).wait()
ccd.capture(frames=5, timeout_s=60, save_path='D:/data/capture.tif').wait()
ccd.save('D:/data/latest.tif', sequence=False, roi_only=False).wait()
```

## 지연과 메모리

카메라 SDK 호출과 이온 검출은 하나의 로컬 프로세스가 담당합니다. 대용량 프레임을 Pipe로 직렬화하지 않고, 잠금으로 보호된 공유 메모리 최신 프레임 슬롯을 사용합니다. 명령/완료 메시지만 Pipe를 통과합니다. UI가 읽는 동안 새 preview 쓰기를 생략해도 이온 검출과 촬영 저장은 계속됩니다.

UI는 약 30Hz로 최신 화면을 표시합니다. 모든 촬영 프레임을 화면에 순서대로 쌓지 않습니다. 별도의 저장 스레드 하나만 허용하고 저장 중복 요청은 거부합니다. 원본 버퍼는 최대 50장 또는 256MiB 이내입니다. 저장 중에는 기존 프레임 참조가 유지되므로 라이브 버퍼와 저장 스냅샷 합계가 약 두 배가 될 수 있습니다. 고정 preview 슬롯은 최대 4096×4096 uint16(약 32MiB)이며 더 큰 영상은 명시적으로 거부합니다. 유한 촬영 장수가 버퍼 한도를 초과하면 시작 전에 거부합니다.

장시간 무손실 스트리밍 저장을 구현한 것은 아닙니다. SDK/USB에서 누락된 프레임은 소프트웨어가 복구할 수 없습니다. 프레임 간격을 검출해 조건 판정에서 연속성을 보수적으로 처리합니다. 빈 SDK 조회에는 짧은 대기를 두며 실제 대기 해상도는 Windows 타이머에 영향을 받습니다.

화면의 `received→display`는 애플리케이션 수신부터 화면 갱신 함수까지의 나이이며 센서 노출/USB 전송/모니터 표시 지연은 포함하지 않습니다. `verification_v7/ccd_smoke.json` (검증 실행 시 생성)도 더미 영상 측정치입니다. 실제 카메라의 latency 보장은 실기 측정 후 가능합니다.

## 이번 범위에 포함되지 않은 장비 제어

CCD 영상·검출은 로컬로 실행합니다. EC 오븐과 셔터는 별도 QCoDeS operation을 통해 CCD 화면의 EC oven 기능과 연동했습니다. [오븐 로딩 안내](OVEN_LOADING_KO.md)를 참고하세요. 일반 Wait for ions만 실행하면 다른 장비를 끄지 않으며, Oven ON 또는 load_oven 작업에서만 자동 OFF/닫기를 처리합니다. Flip mirror·하드웨어 TTL 트리거·EMCCD는 이번 기능에 포함하지 않습니다.

## 검증

`python -m unittest tests.test_v7_ccd -v`는 더미 프로세스로 실제 multiprocessing/공유 메모리/검출/취소/timeout/재연결/저장을 검증합니다. `python verify_ccd_v7.py`는 더미 대형 영상과 기존 메인 UI의 화면 갱신 및 숨겨진 탭에서의 조건 대기를 확인합니다. 실제 SDK/장비 호출은 하지 않습니다.
