# 실험 데이터 저장 위치

기본 경로는 실행 위치와 무관하게 저장소의 `labremote/data`입니다.

- `scans`: XY/XYZ scan 원본, 설정, fitting, 이미지
- `characterization`: fluorescence, Rabi, Ramsey, SPAM, initialization 및 주파수 sweep
- `decay`: 모든 decay 측정
- `ccd`: CCD 이미지
- `queues`: queue 실행 기록과 workflow 실행 폴더

기존 저장 형식과 run별 폴더 생성은 유지합니다. 기존 데이터는 이동하거나 삭제하지 않습니다.
이전 기본값 `logs/fiber_scan`, `data/characterization` 등은 저장 시 새 경로로 연결됩니다.
사용자가 UI/API에서 명시적으로 지정한 별도의 사용자 경로는 유지됩니다.
설정·역할 매핑 JSON은 데이터가 아니므로 기존 config 경로를 유지합니다.

`/labremote/data/` 전체는 Git에서 제외됩니다. 별도 PC로 데이터가 필요하면 직접 복사하세요.
이미 과거 커밋에 포함한 데이터는 ignore만으로 기록에서 지워지지 않습니다.

## Scan 탭별 저장

공통 기본 경로를 사용하면 Scan 1~4는 각각 `scans/EA_collection`,
`scans/EA_excitation`, `scans/EC_collection`, `scans/EC_excitation`에 저장합니다.
각 폴더 아래에 기존처럼 측정 시각과 고유 ID의 실행 폴더가 생성됩니다.
UI의 저장 경로와 Load scan setting 시작 폴더도 각 탭 폴더입니다.
Workflow의 scan 번호에도 같은 규칙을 적용합니다. 과거 기본 경로도 자동 변환합니다.
직접 지정한 사용자 폴더는 그대로 사용하며, 기존 결과는 자동 이동하지 않습니다.

## 실험별 기본 하위 폴더

- `characterization/EA|EC/fluorescence|rabi|ramsey|spam|initialization/YYYY-MM-DD/`
- `decay/EA|EC/171_single|174_single|171_interferometer|174_interferometer/YYYY-MM-DD/`
- `input_counts/<선택한 FPGA 입력 이름>/` (예: PMTA, PMTC, PMTFA, PMTFC)

Input counts는 Save CSV log를 체크해야 저장되며 CSV 열과 측정 방식은 그대로입니다.
Daily/Decay는 위 경로 아래에 기존 실행별 폴더가 생성됩니다.
UI와 workflow API가 동일한 경로 규칙을 사용합니다. 별도로 지정한 사용자 경로 및
주파수 sweep archive의 point 폴더는 그대로 유지합니다. 기존 파일은 이동하지 않습니다.
전체 경로는 기존 `/labremote/data/` Git 제외 규칙에 포함됩니다.

## Scan 이미지

측정 데이터와 같은 실행 폴더에 XY `heatmap.png`가 저장됩니다.
Z scan은 측정한 각 XY 평면을 `heatmap_z_0000.png` 등으로 저장하며,
`z_mfd.png`에 Z 좌표 대비 장축·단축 MFD를 함께 저장합니다.
XY 이미지에는 유효한 fitting의 회전 타원이 표시됩니다.
Z–MFD의 fitting 실패 지점은 빈 구간으로 표시합니다. 중단·실패한 scan은 기존 정책대로
fit 결과를 확정하지 않으므로 Z–MFD 이미지에 유효한 fit 없음이 표시될 수 있습니다.
이미지 저장은 종료 정리 시 수행하며, 원본 데이터·저장 형식은 유지합니다.

날짜는 실험 시작 시 UI PC의 로컬 날짜로 결정합니다. 실행 도중 자정이 지나도 같은 실행 폴더를 유지합니다. 이전에 저장된 자동 날짜 경로는 다음 실행 시 당일로 갱신하며, 사용자가 지정한 별도 저장 경로와 workflow sweep 하위 경로는 그대로 유지합니다. 기존 데이터는 이동하지 않습니다.


## 모든 측정 기본 경로의 날짜 분류

아래 YYYY-MM-DD는 측정/기록 시작 시 저장 PC의 로컬 날짜입니다.

- scans/EA_collection|EA_excitation|EC_collection|EC_excitation/YYYY-MM-DD/실행폴더
- characterization/EA|EC/실험종류/YYYY-MM-DD/실행폴더
- decay/EA|EC/동위원소_모드/YYYY-MM-DD/실행폴더
- input_counts/입력채널/YYYY-MM-DD/CSV
- ccd/EA|EC/YYYY-MM-DD/TIFF 또는 PNG
- pid/장비이름/YYYY-MM-DD/CSV 및 JSON
- mso7054/장비이름/peak_history/YYYY-MM-DD/CSV
- queues/YYYY-MM-DD/queue실행폴더 (Queue 탭 자체가 분류 단위)
- dac/EA|EC/YYYY-MM-DD/runs/요청ID (서버와 UI 양쪽)
- characterization/series/YYYY-MM-DD/series실행폴더 (EA/EC와 실험 종류를 지정한 recipe는 해당 실험 폴더 사용)

진행 중 자정이 지나도 해당 실행의 파일은 분리하지 않습니다. 이전 자동 날짜 경로를
다음 실행에 재사용하면 당일 날짜로 변경합니다. 직접 지정한 custom 경로와 workflow
sweep의 point 폴더는 그대로 유지합니다. 이미 저장된 파일은 이동하지 않습니다.
반복해서 불러오는 DAC 프리셋/sequence 원본은 라이브러리이므로 기존 위치를 유지합니다.
설정 파일과 logs/operations의 진단 기록은 측정 데이터 경로 변경 대상이 아닙니다.
서버 DAC 기록에도 적용하려면 trap_dac/service.py를 서버에 옮긴 뒤 해당 서버를 재시작합니다.
labremote/data와 모든 하위 날짜 폴더는 기존 Git ignore 규칙으로 제외됩니다.
