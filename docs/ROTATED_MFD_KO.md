# 회전 타원 MFD 피팅

완료된 XY scan 또는 각 Z 평면에 회전된 2차원 Gaussian을 피팅합니다.

```text
u = (x-x0) cos θ + (y-y0) sin θ
v = -(x-x0) sin θ + (y-y0) cos θ
I = B + A exp[-2 ((u/w1)² + (v/w2)²)]
```

장축/단축 MFD는 1/e² 반경의 두 배입니다. 장축 ≥ 단축으로 정규화하고, 회전각은 +X에서 +Y 방향(반시계)으로 측정한 장축 방향입니다. 범위는 0 ≤ θ < 180°이며 180° 차이는 같은 타원입니다.

UI에는 Major MFD, Minor MFD, θ, R²가 표시됩니다. 영상 위 타원과 저장되는 heatmap PNG에도 같은 장축·단축·회전을 적용합니다. Z–MFD 그래프는 각 Z에서의 Major/Minor를 보여줍니다. 피팅 실패 평면은 빈 구간으로 표시됩니다.

거의 원형(장축/단축 < 1.05)이거나 추정 각도 불확도가 30° 이상/유효하지 않으면 angle uncertain 경고를 표시합니다. 이 경우 숫자 각도는 optimizer 결과일 뿐 신뢰할 방향으로 해석하지 마세요. 낮은 R², 스캔 경계 부족, 폭 불확도 등 기존 품질 경고도 유지합니다.

`result.json`의 기존 fit/z_fits 안에 다음 필드가 저장됩니다.

- `model`: rotated_elliptical_gaussian_v2
- `coupling_mfd_major_um`, `coupling_mfd_minor_um`
- `angle_deg`, `angle_std_deg`, `angle_reliable`
- `mfd_major_std_um`, `mfd_minor_std_um`

기존 `coupling_mfd_x_um/y_um`, `wx_um/wy_um` 필드는 호환용으로 유지합니다. 회전 모델에서는 중심을 지나는 X/Y 방향 단면의 폭이며 장축/단축 또는 축 투영 폭과 다릅니다. 기존 회전 없는 저장 결과도 표시할 수 있습니다.

측정 순서, 모터 이동, counts, points.csv, heatmap.npz 및 저장 폴더 구조는 변경하지 않습니다. 원본 데이터 손실/변환은 없습니다. 이전 파일을 자동 재피팅하지 않으며 새 측정 결과부터 적용됩니다. MFD는 기존과 같은 유효 coupling-profile 직경으로, 별도 광학 보정 없이 고유 fiber MFD로 해석하지 않습니다.

UI PC 업데이트: labremote/devices/fpga/scan_model.py, labremote/ui/motor_scan_tab.py, labremote/runtime/motor_scan_runner.py. 서버 드라이버 변경 없이 GUI를 재시작하세요.
