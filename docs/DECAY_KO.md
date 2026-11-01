# Decay

FPGA 창에는 기존 FPGA Local과 Daily Characterization 옆에 Decay가 있습니다. Decay 내부는 EA/EC 두 그룹이며 각 그룹에 171, 174, 171 Interferometer, 174 Interferometer 탭이 있습니다. 모두 같은 연결된 FPGA worker를 공유하고 다른 FPGA 실험과 동시에 실행하지 않습니다.

## 모드와 기본 매핑

| 모드 | 초기화 | PMT |
|---|---|---|
| EA/EC 171 | pulse 전 EOM 초기화 | PMTA |
| EA/EC 174 | EOM 초기화 없음 | PMTA |
| EA/EC 171 Interferometer | pulse 전 EOM 초기화 | PMTA, PMTC |
| EA/EC 174 Interferometer | EOM 초기화 없음 | PMTA, PMTC |

EA는 AOMA/EOM_7GA1/2/EOM_2GA, EC는 AOMC/EOM_7GC1/2/EOM_2GC를 기본으로 사용합니다. SYNC와 TRIG는 현재 FPGA hardware definition의 같은 이름입니다. 각 탭에서 역할 매핑을 독립적으로 변경할 수 있습니다. 중복된 활성 output 또는 PMT/SYNC input은 실행 전에 거부합니다. 단일 PMT 모드에서는 PMT2, 174에서는 EOM 역할을 사용하지 않습니다.

원본 코드의 slow output도 설정으로 드러냈습니다. AUX1 기본값은 AOMM이고, 171 일반 모드의 AUX2는 AOMB입니다. 원본처럼 시작/종료 레벨 기본값이 1입니다. 불필요한 AUX는 매핑을 빈 항목으로 선택하면 건드리지 않습니다. cleanup 레벨을 0으로 설정하면 종료/Stop/실패 시 0으로 보냅니다. slow port의 이전 레벨을 읽어 복원하는 기능은 아닙니다.

## 설정과 실행

기본 JSON은 `labremote/config/operations/decay/EA_171_single.json` 등의 8개 파일입니다. `Save settings / mapping`은 같은 이름의 `.local.json`에 저장합니다. `Load settings / mapping`, `Save as`로 실험 조건을 재사용할 수 있습니다.

1. 기존 FPGA Local에서 연결합니다.
2. Decay에서 EA/EC 및 isotope/PMT 모드를 고릅니다.
3. 조건·입력/출력 매핑·AUX 시작/종료 레벨을 확인하고 저장 폴더를 지정합니다.
4. Run을 누릅니다. Stop은 FPGA 시퀀스를 멈추고 수신한 부분을 저장합니다.

시간 설정에서 clocks는 sequencer 10 ns 단위입니다. Stopwatch histogram의 한 bin은 원본과 동일한 1.25 ns입니다. 서로 다른 단위입니다. `TIME_INIT`는 171에서 초기화 시간이고, 174에서는 원본에 있던 추가 AOM ON hold 시간입니다. 174에 EOM 초기화를 추가하지 않았습니다. 2-PMT 원본은 짧은 냉각 구간에도 AOM-off wait 변수를 사용하므로 AOM-on wait 설정은 단일 PMT 모드에만 적용됩니다.

`SIGNAL_THRESHOLD`는 수집할 시간차의 하한 bin, `DECAY_THRESHOLD`는 prompt/decay를 구분하는 표시·집계 경계입니다. 171 Interferometer는 원본처럼 각각 82/85입니다. histogram bins는 3의 배수이며, 선택 PMT 수에 맞춰 메모리를 분리합니다.

한 PC batch의 pulse trials는 `run_number × outer_loop_in_fpga × wo_cooling_number`입니다. 전체 반복은 여기에 `outer_loop`를 곱합니다. 원본의 사용되지 않는 호스트 변수·메일 알림·하드코딩 serial port는 가져오지 않았습니다.

## 원본과 비교한 수집 보완

FPGA 메모리는 bin당 16비트입니다. overflow를 피하려고 한 hardware chunk의 pulse trials를 65535 이하로 제한하며, cooling group 경계에서 나눕니다. `outer_loop_in_fpga` 반복도 host에서 관리합니다. 총 pulse 횟수와 구간 내부의 원본 pulse 명령은 유지되지만, chunk 사이에 PC 전송·재업로드 대기가 있습니다. 하나의 PC batch에 여러 chunk가 포함될 수 있습니다. SYNC stopwatch가 실제로 도착한 trial만 histogram에 넣는 확인 명령을 추가했습니다.

한 실행 전체는 `DECAY_ACQUIRE` operation 하나입니다. timeout은 hardware chunk별로 적용됩니다. 정상·중단·오류 종료 시 TRIG LOW, 선택 AOM ON, 171의 EOM7G ON/EOM2G OFF와 설정된 AUX cleanup 레벨을 보냅니다. 외부 RF·MW 장비에는 명령을 보내지 않습니다. 기존 FPGA 연결과 hardware definition을 사용하며 새 server driver가 필요하지 않습니다.

## 그래프와 저장

완료된 hardware chunk마다 네 그래프를 갱신합니다.

- PMT별 누적 decay histogram 및 고정 수명 기준선
- PC batch별 decay counts (진행 중 batch는 부분 합계)
- 가장 최근 완료된 hardware chunk histogram
- PMT를 합한 누적 prompt window

기준선의 기본 수명 8.12 ns는 원본의 **고정 기준값**이며 측정으로 추정한 fitting 결과가 아닙니다. 각 탭에서 reference lifetime을 변경할 수 있습니다. signal threshold와 decay boundary가 같으면 prompt window가 비어 있는 것이 정상입니다. PC batch 그래프의 counts는 초당 rate가 아닙니다.

결과는 `data/decay` 또는 지정한 폴더의 실행별 고유 디렉토리에 저장됩니다.

| 파일 | 내용 |
|---|---|
| configuration.json | 원래 요청 조건, 역할 매핑, FPGA/HD 정보, 두 시간 단위, 소스 해시 |
| source/ | 사용한 decay 코드와 HD/operation 사본 |
| raw_fifo.csv | batch/chunk별 수신 원시 histogram word와 tag/검증 결과 |
| chunks.jsonl | 완료된 chunk별 histogram, 실제 groups/trials/경과시간 |
| histogram.json | 누적값, 최신 chunk, batch별 집계, 실제 완료 trials |
| histogram.csv | bin, 시간(ns), PMT별 누적 counts |
| decay.png | 마지막 결과 이미지 |
| result.json | 완료/중단/실패 및 완료 batch 수 |

FPGA가 아직 전송하지 않은 내부 histogram은 Stop 시 복구할 수 없습니다. 전송 도중 중단된 chunk의 수신 word는 raw_fifo.csv에 남지만, 완전한 chunk가 아니므로 누적 histogram에는 넣지 않습니다. 파일을 0으로 채워 정상 측정처럼 처리하지 않습니다. `Open result`에서 해당 탭과 동일한 chamber/mode의 result.json을 열어 다시 표시합니다.

## Workflow API

```python
def main(devices):
    result = devices.fpga('fpga_local').run_decay(
        'EC', '171_dual',
        directory='D:/ExperimentData/Decay',
    ).wait()
    print(result['status'], result['folder'])
```

`settings` 또는 `settings_file`로 조건을 전달할 수 있고, 생략하면 해당 탭의 local/default JSON을 사용합니다. 모드는 `171_single`, `174_single`, `171_dual`, `174_dual`입니다. 중단은 `stop_decay()` 또는 handle.request_cancel()입니다. 기존 ExperimentArchive의 point 디렉토리를 directory로 넘겨 다른 실험과 함께 보관할 수도 있습니다.
