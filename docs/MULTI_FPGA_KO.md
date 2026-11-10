# 여러 FPGA와 장비별 핀 매핑

## 연결과 식별

메인 화면 또는 장비 메뉴의 **로컬 FPGA 검색 / 연결**에서 COM 포트를 선택하고
저장 데이터에 사용할 별명을 입력한다. 연결하면 FPGA별 독립 창이 열린다.
각 창에 Manual, Input counts, motor scans, Daily characterization, Decay, HOM,
Entanglement, Ion Check, Micromotion, etc가 포함된다.

고유 USB serial number가 있으면 VID/PID/serial로 기존 `fpga_1`, `fpga_2` 등의
장비 ID를 찾는다. 고유 serial이 없거나 중복되면 새 순차 ID를 만든다.
이 경우 재시작 후 실물 장비를 자동으로 동일 장비라고 추정하지 않는다.
이미 연결된 COM 포트를 다시 선택하면 기존 창을 연다. 같은 포트의 중복 연결도
worker에서 차단한다. 검색 자체는 포트를 열지 않으며 연결 시 버전을 확인한다.

별명은 데이터 폴더 이름이다. Workflow에서는 별명이 아닌 **고유 장비 ID**를
사용한다. 기존 `fpga_local` ID와 그 기본 실험 설정도 계속 사용할 수 있다.
창 닫기는 창 숨김이며 연결 해제나 실험 중지를 뜻하지 않는다.

## 핀 번호와 이름

`ja_0..ja_7`, `jb_0..jb_7`, `jc_0..jc_7`, `jd_0..jd_7`의 32개 신호가 항상 존재한다.
이 번호는 커넥터 접점 번호 또는 시퀀서 비트 번호가 아니다.
현재 Sequencer v4_03 정의에서 `ja_3`은 port 0 bit 15, `jc_0`은 port 2 bit 0,
`jd_0`은 port 2 bit 8이다. `jb_0/2/4/6`은 counter/stopwatch 입력이고,
`ja_2`는 stopwatch 입력이다. 나머지 JA/JB는 빠른 출력, JC/JD는 slow 출력이다.

**FPGA Configuration**에서 32개 핀의 사용자 이름을 변경하거나 JSON을 불러온다.
기존 PMTA/AOMA 등의 기본 이름과 실제 연결은 유지되며, 기존에 이름이 없던
출력은 `JC0`, `JD0` 같은 이름을 갖는다. 입력/출력 기능과 내부 주소는 편집할 수 없다.
부분 설정의 누락 핀은 기본값으로 채운다. 알 수 없는 핀, 중복 이름, 잘못된
입출력 연결은 거부한다. FPGA 자체의 펌웨어 핀 배치를 바꾸는 기능은 아니다.

보드 핀 이름/별명 변경은 연결 해제 후 수행한다. 실행 중에는 매핑 변경을 거부한다.

## 실험 역할

각 실험의 **실험 신호 → FPGA 핀 이름**을 펼쳐 역할을 연결하고 저장한다.
예를 들어 HOM의 PMTA 역할을 `Detector_Left [jb_4]`에 연결할 수 있다.
FPGA에 PMTA라는 사용자 이름이 존재할 필요는 없다.
기존 실험 변수의 PMTA/AOMA 등은 논리적 역할 선택이며, 이 표가 실제 핀을 결정한다.
매핑은 FPGA별·실험 종류별로 저장된다. EA/EC 변수 설정은 기존처럼 별도 유지된다.

Micromotion은 기존 TRG/PMT/counter 선택란에서 장비의 핀 이름과 신호 ID를 함께 표시한다.
etc의 phase hold/Ramsey는 기존 nickname 선택란에서 해당 FPGA의 16개 slow 출력 중
12개를 선택한다. 새로운 보드 정의에서 이름 없는 slow 출력이 누락되지 않는다.

Counter/stopwatch 지원과 빠른/slow 출력 제약은 유지된다. 사용하지 않는 논리 역할끼리
같은 핀을 가리킬 수 있지만, 실험에서 동시에 쓰는 역할의 충돌은 실행 전에 검사한다.
시퀀스의 기본 핀, 명령, 타이밍 및 cleanup 레벨은 기존 구현을 유지한다.

## Workflow

```python
def main(devices):
    fpga = devices.fpga('fpga_2')
    print(fpga.pin_names())  # 신호 ID -> 이 장비의 사용자 이름
    fpga.set_output('Cooling', True).wait()
    counts = fpga.measure_counts('Detector_Left', 100, 10).wait()

    # 저장된 실험 매핑을 이번 호출에 한해 사용자 핀 이름으로 덮어쓴다.
    with fpga.pin_mapping('hom', {'PMTA': 'Detector_Left'}):
        result = fpga.run_hom().wait()
    return result
```

숫자 counter channel을 사용하는 기존 코드는 그대로 동작한다.
`pin_mapping`은 영구 설정을 변경하지 않는다. 실행 중인 runner와 큐 명령은
각자의 매핑 스냅샷을 유지한다. 실험 탭에서 Queue에 추가할 때 매핑도 함께 저장하고,
일반 Queue/Workflow 시작 시 연결된 FPGA 프로필을 고정한다.
새 FPGA 창의 기본 Daily workflow는 해당 장비 ID가 지정된 로컬 사본이다.

외부 시퀀스 파일은 `build_program(parameters, hd=None)` 형식이면 선택한 FPGA의
정의를 전달받는다. 사용자가 직접 기존 vendor 모듈이나 물리 비트를 하드코딩한
외부 Python 파일은 자동 변환하지 않는다. 장비별 이름을 사용할 파일은 전달받은
`hd`를 사용해야 한다. 기존 인자 하나의 builder도 계속 실행할 수 있다.

## 저장과 Git

- `labremote/config/devices/fpga/<장비 ID>.local.json`: 별명, 32개 핀 이름, 실험 매핑.
- `registry.local.json`: USB 식별과 순차 장비 ID.
- `ports.local.json`: 기존 성공 연결 포트 기록.
- `settings.local/<장비 ID>/...`: 장비별 실험 변수 설정.
- `workflows.local/<장비 ID>/...`: 장비별 기본 workflow 사본.

위 로컬 파일/폴더는 `.gitignore`로 제외한다. 기존 `fpga_local`의 실험 변수 파일은
호환성을 위해 기존 위치를 유지한다. 공개 기본 설정과 로컬 설정을 구분한다.
결과는 기존 날짜/실험 경로 아래 별명 폴더에 저장하고 각 실험 실행 폴더의
`fpga_mapping.json`에 적용한 장비 ID, 별명, 핀 이름, 역할 매핑을 남긴다.
Input counts CSV에는 같은 이름의 `.mapping.json` 파일을 남긴다.

## 중지와 연결 해제

연결 해제는 새 요청 접수 중단 → 대기/실행 작업 취소 → runner cleanup/저장 완료
→ sequencer STOP → serial close 순서로 처리한다. 모든 출력을 일괄 OFF하지 않으며
기존 실험의 cleanup 상태 또는 마지막 수동 출력 상태를 유지한다.
USB 단절/통신 실패에서는 STOP과 출력 cleanup을 확인할 수 없음을 표시한다.
독립 FPGA의 작업은 계속 진행된다. 같은 workflow에 묶인 작업의 취소 전파는 유지된다.

FPGA별 worker FIFO와 기존 runner가 명령 실행을 담당한다. 별도 FPGA 실험들이
같은 모터/DAC/RF 장비를 공유하는 경우의 실험적 충돌 방지 규칙은 추가하지 않았다.
그 조합은 사용자가 관리한다. 실제 두 보드와 케이블의 전기적 검증은 별도로 필요하다.
