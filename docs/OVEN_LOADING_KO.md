# CCD 화면에서 EC 오븐으로 이온 로딩

서버에 등록된 E3631A `oven_psu`와 RPiOven `oven_relays`를 사용합니다. 제공된 QCoDeS 드라이버의 parameter get/set 계약을 사용하며 서버나 Raspberry Pi에 자동 배포하지 않습니다. 기본 InstrumentServer 주소는 앱 상단 Host/Port입니다. Connect oven devices는 ID와 실제 PSU 출력 상태·측정 전압/전류, 릴레이 상태를 읽어서 연결을 검증합니다. 출력을 켜거나 릴레이를 바꾸지 않습니다.

## 설정과 사용

1. 실제 CCD를 Thorcam으로 연결합니다. Dummy CCD를 연결한 상태에서는 실제 오븐 ON을 거부합니다.
2. CCD 탭 오른쪽의 EC oven 영역에서 Connect oven devices를 누릅니다. 기본 이름은 oven_psu / oven_relays이며 화면에서 바꿀 수 있습니다.
3. 기본 EC 셔터는 shutter_2입니다. 실제 배선에 따라 shutter_1 또는 shutter_2를 선택합니다. 별도의 연결 확인 체크박스는 없습니다. 이 선택을 임의로 물리적 검증된 것으로 간주하지 않습니다.
4. 171 또는 174를 선택합니다. 기존 Ion detection의 threshold, 최소 면적, ROI, 목표 개수, 연속 프레임 수를 확인합니다. 이온 조건은 밝은 연결 영역 count >= target의 연속 판정이며 기존 CCD 알고리즘을 그대로 사용합니다.
5. Oven ON을 누르면 아래 순서로 실행합니다. STOP / Oven OFF로 중단할 수 있습니다.

| 선택 | 출력 | 전압 제한 | 전류 제한 |
|---|---|---|---|
| EC 171 | CH1 / P6V | 5.000 V | 1.30 A |
| EC 174 | CH1 / P6V | 5.000 V | 1.40 A |

EA 171/174의 5.000 V / 0.75 A 값은 profile에 보존하지만 이번 UI는 EC만 실행합니다. Flip mirror는 조작하지 않습니다. 선택하지 않은 셔터도 조작하지 않습니다.

## operation 순서

1. `OVEN_OFF`: E3631A 전체 출력 OFF 및 readback. 세 출력의 측정 전류가 각각 20 mA 이하인지 최대 5초 동안 확인한 뒤에만 다음 단계로 갑니다.
2. `OVEN_SHUTTER_CLOSE`: 선택한 EC 셔터 닫기.
3. 기존 CCD 촬영을 멈추고 선택한 검출 설정을 적용한 뒤 연속 촬영을 시작합니다. 진행 중인 CCD 작업이나 ion wait가 있으면 시작 전 거부하므로 먼저 완료/취소하세요.
4. `OVEN_ROUTE`: EC_171 또는 EC_174 선택 및 GPIO 상태 readback.
5. `OVEN_CURRENT_SETUP`: tracking OFF, CH2/CH3 전압·전류 설정을 0으로 만들고 CH1 전류·전압을 설정합니다. E3631A의 OUTP는 전체 출력에 공통이므로 이 PSU는 오븐 전용으로 사용해야 합니다.
6. `OVEN_SHUTTER_OPEN`: route 확인 후 EC 셔터 열기.
7. `OVEN_ON`: 설정과 미사용 채널을 재확인하고 전체 출력 ON.
8. `CCD_WAIT`: 새로운 프레임에서 목표 조건을 기다립니다. 별도 카메라 프로세스가 판정하므로 다른 탭을 보고 있어도 동작합니다. PSU 측정 V/A와 route/shutter 상태를 주기적으로 읽습니다.
9. 성공·실패·취소·timeout 모두 `OVEN_OFF` → `OVEN_SHUTTER_CLOSE`를 실행합니다. 한 종료 operation이 실패해도 다른 종료 operation은 별도로 시도합니다.

10분(600초)은 setup을 포함한 task 실행 시작부터의 제한입니다. UI Ion detection의 별도 Timeout s 입력으로 이 제한을 늘릴 수 없습니다. timeout 이후 OFF/CLOSE 확인 작업이 추가로 진행됩니다. 진행 중인 통신 및 readback을 중간에 잘라 성공으로 처리하지 않으므로 실제 종료 완료 시점은 통신 응답 시간만큼 늦어질 수 있습니다.

전류/전압 표시는 CH1 측정값이며 실제 전류는 부하와 전압 제한에 따라 설정 전류보다 낮을 수 있습니다. 종료 후 CCD 연속 영상은 유지합니다. 앱을 정상 종료하면 오븐 task 취소·종료 처리를 기다린 다음 worker를 닫습니다. 통신 오류로 OFF/CLOSE를 확인하지 못하면 명시적인 오류를 표시합니다.

이 기능은 클라이언트의 정상 실행 중 timeout/취소 처리입니다. PC 강제 종료·프로세스 강제 종료·네트워크 단절 시 물리적 전류 차단을 보장하는 서버/하드웨어 watchdog은 제공된 드라이버에 없습니다. GPIO readback도 실제 셔터 접점의 물리적 피드백은 아닙니다.

## workflow

UI와 workflow는 같은 큐·operation·readback·종료 처리를 사용합니다. 먼저 CCD 화면에서 실제 CCD 및 오븐 장비를 연결하고 EC 셔터를 선택하세요. 실행 예제는 [load_ec_ions.py](../labremote/workflow/load_ec_ions.py)입니다.

```python
def main(devices):
    from labremote.devices.oven.settings import load_settings
    local = load_settings()
    result = devices.ccd().load_oven(
        171, shutter=local['shutter'],
        threshold=1000, min_area=3, target=1, consecutive_frames=3,
    ).wait()
    print(result)
```

오븐 task 중에는 충돌하는 CCD 연결·설정·추가 촬영 작업을 거부합니다. 명시적인 CCD stop/disconnect는 허용되며 진행 중인 이온 대기를 실패시켜 오븐 종료 처리로 이어집니다. 장비를 별도의 앱/서버 클라이언트에서 동시에 조작하는 것은 보호하지 못합니다.

장비 이름과 셔터 선택은 `labremote/config/oven.local.json`에 저장합니다. 기존 `*.local.json` 규칙으로 Git에서 제외됩니다. 다른 UI PC에서도 같은 선택을 유지하려면 이 파일을 직접 복사하거나 화면에서 다시 설정하세요. 서버 드라이버 폴더 구조, 기존 실행 배치 파일과 Git 설정은 이번 기능 추가로 변경하지 않습니다.

## PSU 시리얼 오류 복구

E3631A 드라이버는 timeout/불완전 응답 때 서버의 serial 핸들을 닫습니다. 이후 `connection invalid`는 첫 오류의 후속 결과입니다. UI의 Connect는 기존 원격 인스턴스에 붙는 동작이므로 닫힌 serial 핸들을 재생성하지 않습니다. 장비 전면에서 출력 상태를 확인하고 필요하면 수동 OFF한 뒤, 서버에서 oven_psu 인스턴스를 명시적으로 재생성하거나 다른 실험을 정지한 상태에서 서버를 재시작해야 합니다.

장비 operation 오류가 발생하면 자동 조회와 새 오븐 로딩을 중지합니다. 서버를 복구한 다음 Connect oven devices를 눌러 실제 응답이 확인되어야 재개합니다. STOP/OFF 및 셔터 닫기 시도는 이 제한과 별개로 유지합니다. ON이나 실패한 설정 쓰기를 자동 재시도하지 않습니다.

`get_idn()`은 캐시된 정보여서 기존 Connect 성공만으로 RS-232 통신 정상 여부를 알 수 없었습니다. 현재 연결 검사에는 실제 readback이 포함됩니다. 설정이 맞는데도 `SYST:ERR?`가 응답하지 않는 원인은 현장의 질의 응답/동일 포트 사용/케이블 상태 확인이 필요하며 timeout 증가나 오류 조회 생략으로 숨기지 않습니다.

## 간소화된 CCD 연결 화면

카메라 serial·DLL 입력칸은 제거했습니다. 기존 로컬 CCD 설정값은 유지되며, 없으면 한 대의 카메라를 자동 선택하고 기존 기본 DLL 경로를 사용합니다. 여러 카메라 또는 별도 SDK 경로가 필요하면 로컬 client_settings.json의 ccd_options에서 지정합니다.

오븐의 설정 제한값과 현재 측정값은 별도로 표시합니다. 현재 측정값은 PSU의 ch1_measured_voltage/current 조회 결과입니다. 연결 전에는 —, 오류 시에는 조회 실패를 표시하며 설정값을 측정값처럼 표시하지 않습니다.
