# 그룹별 Queue Monitor

GUI 재시작 후 Queue를 구성하거나 불러오면 **Queue Monitor → 그룹별 모니터**에 해당 그룹과 workflow의 빈 모니터가 자동으로 만들어집니다. Queue 실행 중에는 같은 화면에 결과가 누적됩니다. 기존의 상태·metrics 그래프는 **전체 실행 목록**에 있습니다.

## 화면과 집계 단위

- 왼쪽: Repeat group 선택과 완료 회차. `실행 중 그룹 따라가기`를 켜면 현재 실행 그룹으로 이동합니다. 목록을 직접 클릭하면 따라가기가 해제되어 이전 그룹을 계속 확인할 수 있습니다.
- 그룹 내부: 각 Queue 항목의 Ion Check, SPAM, Entanglement 모니터. 같은 파일을 두 번 배치해도 job ID가 다르므로 별도 모니터입니다. 그룹 없는 항목도 독립 모니터가 됩니다.
- 전체 Queue 반복은 별도 그룹 화면으로 나눕니다. 예를 들어 전체 반복 1의 ZZ와 전체 반복 2의 ZZ는 섞이지 않습니다.
- 아래 표: 그룹 회차, workflow, 작업 반복, 실행 상태, 결과 요약, 실행 시간. 행을 선택하면 원래 상태/metrics와 결과 경로를 확인할 수 있습니다.
- `저장된 Queue 열기`: queue_manifest.json을 열면 저장된 원시 결과로 동일한 모니터를 재구성합니다. `현재 Queue 보기`로 실시간 화면에 복귀합니다.

## 측정별 표시

**Ion Check**: A/B/C fluorescence의 회차별 마지막 측정값을 선으로 표시합니다. 재측정을 포함한 모든 측정은 흐린 점으로 표시합니다. 정상 실행 수, 최근 판정, 총 측정 수와 재측정 수를 표시합니다. Threshold가 다른 결과는 별도 설정 패널로 분리합니다. 기존 frozen ion_check_workflow.py의 반환 history도 지원합니다.

**SPAM**: EA/EC 회차별 SPAM fidelity와 그룹 누적 fidelity를 표시합니다. 누적은 각 상태의 N_error/N_received를 합산한 뒤 두 상태의 오류율을 동일 가중합니다. 회차별 fidelity의 단순 평균이 아닙니다. 완료된 챔버 실행만 포함하고 실패·중단 실행은 제외 수를 표시합니다. 같은 챔버의 설정이 달라지면 별도 선·누적값으로 표시합니다.

**Entanglement**: 기존 Accumulator, decay fit, coincidence bin, geometric_bins, decay_reference 계산을 재사용합니다.

- Decay counts: PMTA, PMTC, Total 및 decay fit, 채널 cutoff
- Coincidence: PMTC−PMTA 지연 분포와 herald window
- 로그 기하분포: herald까지의 **시도 횟수 N**을 로그 축으로 표시합니다. PC 경과시간(초) 분포가 아닙니다. Exhausted batch도 확률 분모에 포함합니다.
- `그룹 누적 / 최신 회차 / 회차 선택`으로 표시 범위를 전환합니다. 최신 회차는 결과가 저장된 가장 최근 회차입니다.
- `기존 탭 전체 그래프`는 선택 범위의 결과를 기존 EntanglementPlot에 넘겨 별도 창으로 표시합니다. 상태 확률, state readout histogram, batch별 decay counts/trial 등도 확인할 수 있습니다. 이 창은 열었을 때의 사본입니다.

완료된 유효 FPGA batch만 얽힘 통계에 포함합니다. 중단·실패 실행 안에서 이미 완료된 batch는 유지하고, aborted batch는 제외합니다. 설정이 다른 결과는 합산하지 않고 별도 패널로 나눕니다. 같은 파일을 다시 읽거나 Queue 상태가 갱신돼도 결과를 중복해서 더하지 않습니다.

## 갱신과 파일

하드웨어 polling이나 추가 측정 없이 결과 파일을 백그라운드에서 읽습니다. Queue 상태 변경 시 갱신하며, 실행 중에는 약 1.2초 간격으로 저장된 checkpoint를 확인합니다. 처리 시간이 길면 읽기를 중복 실행하지 않습니다. Ion Check는 samples checkpoint, 얽힘은 results.json의 완료 batch가 반영됩니다. SPAM은 각 챔버의 result.json과 analysis.json 저장 후 반영됩니다.

사용자 정의 workflow도 run_ion_check/run_spam/run_entanglement 호출을 소스에서 확인할 수 있으면 해당 빈 모니터를 생성합니다(소스를 실행하지 않음). helper를 통해 간접 호출하면 실행 결과 형식을 읽은 뒤 전용 모니터로 전환합니다. 그 밖의 workflow에는 기본 상태·결과 표시가 제공됩니다. 결과는 devices.run_directory 아래에 저장하거나 WorkflowResult.result_paths로 반환해야 합니다.

저장된 Queue를 옮길 때는 steps 아래의 측정 결과도 함께 옮겨야 합니다. 결과 파일이 없거나 손상되면 오류를 표시하며 측정값을 만들어 채우지 않습니다. 기존 Queue 파일을 새 형식으로 변환할 필요는 없습니다.

검증은 모의 데이터·모의 장비 기반입니다. 실제 장비 측정은 수행하지 않았습니다.
