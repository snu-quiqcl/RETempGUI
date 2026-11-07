# Queue workflow monitors

Workflow 편집 창의 **Monitor** 탭에서 종류(없음, Ion Check, SPAM, RE), 탭 이름,
기본 표시(그룹 누적/최신 회차)를 설정합니다. RE는 기존 RE 탭의 모든 그래프를 항상 표시합니다.
Queue 목록의 Monitor 열에서 연결 상태를 확인할 수 있습니다.

Monitor 화면에서 그룹을 선택하면 그 그룹에 설정된 Workflow별 탭이 나타납니다.
각 탭에서 그룹 누적, 최신 회차, 특정 회차를 선택할 수 있습니다. Setup은 `없음`으로
설정하면 그래프 없이 공통 실행 목록에 상태가 표시됩니다.

Queue JSON의 각 workflow job에 `monitor` 객체를 저장합니다. 실험 `parameters`와는
독립적이며 실행 로직에 영향을 주지 않습니다. 기존 파일은 읽을 때 소스의 알려진
측정 호출을 바탕으로 추천값을 채웁니다. 간접 호출이나 사용자 정의 workflow는 직접
종류를 지정해야 합니다. 명시된 종류와 결과 파일 종류가 다르면 경고하고 합산하지 않습니다.

```json
{
  "kind": "ent",
  "title": "RE",
  "view": "cumulative"
}
```

결과는 Queue 항목 ID, 그룹 ID, 전체 Queue 반복, 그룹 회차로 구분합니다.
서로 다른 RE/Ion Check 설정은 별도 탭으로 분리합니다. SPAM은 동일 탭에서 챔버와
설정별로 독립 누적하며 미완료 SPAM은 합산하지 않습니다. RE는 완료 FPGA batch만
합산합니다. 실패/중단 workflow 안에 저장된 유효 완료 batch는 포함합니다.

기존 Queue 파일의 `charts` 선택값은 무시하고, 다시 저장하면 제거합니다.
RE는 기존 EntanglementPlot을 재사용합니다. 두 decay 그래프는 로그 Y축,
herald 분포는 로그 간격 trial bin별 확률과 동일 구간 기하분포입니다.
Population은 00/01/10/11 빈도를 herald 수로 정규화하고
`sqrt(p*(1-p)/N)`의 ±1σ 이항 표준오차를 표시합니다. 이는 신뢰구간이 아니며
p=0 또는 1이면 표준오차가 0입니다. Herald가 없으면 오차막대를 표시하지 않습니다.
이 공통 plot 변경은 기존 RE 탭에도 동일하게 적용됩니다.
