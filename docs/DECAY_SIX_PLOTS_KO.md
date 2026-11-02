# Decay 6개 그래프

EA/EC × 171/174 × single/interferometer 총 8개 탭과 저장 이미지에 적용합니다.
시간은 stopwatch bin × 1.25 ns입니다. 시퀀서 명령 clock(10 ns)과 구분합니다.

1. 누적 Decay: Decay threshold 이상, 각 PMT 및 두 PMT 합계와 지수 fitting.
2. 최신 배치 Decay: 현재 마지막 PC batch 내에 수신된 chunk들을 합산. 진행 중이면 partial 표시.
3. 누적 Pulse: Communication threshold부터 Decay threshold + 5 bins(6.25 ns)까지 표시.
4. 최신 배치 Pulse: 3과 같은 표시 범위, 마지막 PC batch만 표시.
5. 배치별 Decay 합계: threshold 이상 counts. 우측 점선은 해당 batch counts / 실제 수신 trials × 100%.
6. 배치별 Pulse 합계: Communication threshold 이상, Decay threshold 미만만 합산. 뒤쪽 preview 제외.

single 모드는 연결된 PMT 한 개만 표시합니다. dual은 PMT1, PMT2, 합계입니다.
합계 counts/trials는 평균 합산 검출 수로, 둘 중 하나라도 검출될 확률과 다릅니다.
threshold bin은 Decay에만 포함하여 중복 집계하지 않습니다. 두 threshold가 같으면 Pulse 합계는 0입니다.
Pulse preview는 수집된 histogram 끝을 넘기지 않습니다. threshold 설정값은 자동 변경하지 않습니다.

Fitting은 누적 counts에 A exp(-(t-t0)/tau)+background 모델을 적용합니다.
sqrt(max(counts,1)) 가중 표준편차를 사용하며 데이터가 부족하거나 fitting이 실패하면 unavailable로 표시합니다.
기존 reference_tau_ns는 옛 설정 호환을 위해 보존하지만 fitting에 사용하지 않습니다.
화면의 데이터는 chunk 수신 시 갱신됩니다. histogram의 16-bit overflow 방지 chunk 분할은 유지합니다.

원본 raw_fifo.csv, chunks.jsonl, histogram.csv와 기존 histogram.json 필드는 보존합니다.
histogram.json의 각 batch에 histograms, prompt_counts_by_channel을 추가합니다.
최종 fit은 decay_fit.json, 6개 그래프는 decay.png에 저장됩니다.
기존 파일에 배치별 histogram이 없으면 마지막 chunk를 batch로 오인하여 표시하지 않고 unavailable로 표시합니다.
기존 누적 데이터와 배치 합계는 계속 열 수 있습니다.
