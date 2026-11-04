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

한 PC batch는 FPGA 한 번 실행으로 수행합니다. `run_number`, `wo_cooling_number`, `outer_loop_in_fpga`를 그대로 FPGA에 전달하며, 내부 chunk 분할이나 배치 중간 재업로드가 없습니다. bin당 16비트 카운터는 그대로입니다. SYNC stopwatch가 실제로 도착한 trial만 histogram에 넣습니다.

한 실행 전체는 `DECAY_ACQUIRE` operation 하나입니다. timeout은 PC batch 전체에 적용됩니다. 정상·중단·오류 종료 시 TRIG LOW, 선택 AOM ON, 171의 EOM7G ON/EOM2G OFF와 설정된 AUX cleanup 레벨을 보냅니다. 외부 RF·MW 장비에는 명령을 보내지 않습니다. 기존 FPGA 연결과 hardware definition을 사용하며 새 server driver가 필요하지 않습니다.

## 그래프와 저장

완료된 PC batch마다 6개 그래프를 갱신합니다. 누적/최신 배치 decay, 누적/최신 배치 pulse, 배치별 decay/pulse 합계를 표시하며 실제 누적 counts에 지수 fitting을 적용합니다. 자세한 내용은 [6개 그래프 설명](DECAY_SIX_PLOTS_KO.md)을 참조하세요.

결과는 `labremote/data/decay` 또는 지정한 폴더의 실행별 고유 디렉토리에 저장됩니다.

| 파일 | 내용 |
|---|---|
| results.json | 전체 설정/포트 매핑, FPGA/HD 정보, 단위와 코드 해시, 실행 시작·종료/상태, 최종 누적 histogram |
| batches.jsonl | 배치마다 started/finished 기록, 시작·종료/시퀀서 시작 요청 시각, 소요 시간, 완료·실패·중단 상태. 완료 배치는 채널별 histogram과 decay/pulse 합계 포함 |
| raw_fifo.csv | run_id, batch, row_index, 원시 histogram word 3개, tag, 수신 패킷 검증 결과. 잘못된 형태는 raw_record에 보존 |
| decay.png | fitting 곡선을 포함한 마지막 결과 이미지 |

새 실행은 위 네 파일만 생성합니다. fitting 수치 JSON과 소스 복사본은 저장하지 않습니다. 코드 해시는 results.json에 보존하며 화면/이미지의 fitting은 유지합니다.

results.json의 schema_version은 2입니다. configuration.settings는 실행에 사용한 내부 설정값이며, configuration.time_settings_us는 시간 설정을 µs로 환산한 값입니다. 시퀀서 1 clock은 10 ns, histogram 1 bin은 1.25 ns입니다. histogram에는 bin/time_ns/channel_names/counts와 완료 배치의 programmed_trials를 저장합니다. programmed_trials는 설정값을 곱한 시행 횟수로, 실제 유효 SYNC 또는 광자 검출 수가 아닙니다.

batch와 row_index는 0부터 시작합니다. 배치 started는 준비 작업 직전, sequencer_started_at은 FPGA 시작 명령 반환 직후, finished_at은 수신/검증 종료 시 PC에서 기록한 시간대 포함 ISO 시각입니다. FPGA 자체의 정밀 타임스탬프가 아닙니다. elapsed_s는 PC의 단조 증가 시계로 계산합니다. 시작만 있고 종료가 없는 배치는 프로그램 강제 종료 등으로 마무리되지 않은 배치입니다.

배치마다 raw와 batches 기록을 flush/fsync한 뒤 results.json을 임시 파일 교체 방식으로 갱신합니다. 비정상 종료 후 결과를 열면 batches.jsonl의 완료 기록으로 histogram을 재구성하고, 마지막에 잘린 JSON 행은 무시합니다. 실행 상태가 running인 채 남은 결과는 interrupted로 표시합니다.

FPGA가 아직 전송하지 않은 내부 histogram은 Stop 시 복구할 수 없습니다. 전송 도중 중단된 배치의 수신 word는 raw_fifo.csv에 남지만, 완전한 배치가 아니므로 누적 histogram에는 넣지 않습니다. raw의 valid는 패킷 검증 결과이지 전체 배치 완료 여부가 아닙니다.

`Open result`에서 해당 탭과 동일한 chamber/mode의 results.json을 엽니다. batches.jsonl은 같은 폴더에 함께 보관하세요. 기존 result.json + configuration.json + histogram.json 형식도 그대로 열 수 있습니다. 결과를 열 때 fitting은 다시 계산합니다.

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

저장 형식 호환을 위해 chunk 필드는 남기되 새 실행은 배치마다 chunk=0 레코드 하나만 기록합니다. FIFO를 여러 패킷으로 읽더라도 측정 반복을 분할하는 것은 아닙니다.
