# CCD 밝기와 Flipper 표시

CCD 영상 바로 아래 Image levels에서 Auto levels, Min, Max를 설정합니다. Auto를 끄면 Min/Max 입력이 활성화됩니다. 원본 픽셀, 저장 영상, 이온 검출 threshold는 바뀌지 않습니다. 시작 기본값은 기존 장비 구성의 ccd_display에서 읽으며 화면에서의 변경은 현재 세션에 적용됩니다. 다음 실행에도 유지할 기본값은 메인 Configuration에서 설정하세요.

Flipper는 위쪽에 연결/연결 해제/위치 읽기, 아래쪽에 큰 Position 1/2 버튼, 각 버튼 아래에 방향 별명과 선택적인 이미지를 표시합니다. 다섯 장비는 스크롤 영역에 표시합니다.

`labremote/config/ui/flipper_display.local.json`을 만들어 아래처럼 실제 서버 이름을 기준으로 설정하세요. 공개 기본 파일 `flipper_display.json`은 빈 설정입니다. 로컬 파일은 Git에서 제외됩니다.

```json
{
  "FLIP_399": {
    "1": {"label": "EA 방향", "image": "flipper_images.local/399_pos1.png"},
    "2": {"label": "EC 방향", "image": "flipper_images.local/399_pos2.png"}
  }
}
```

이름과 방향은 예시입니다. 실제 장비의 광로를 확인해 입력하세요. image는 생략하거나 빈 문자열로 둘 수 있습니다. 상대경로는 설정 JSON이 있는 폴더 기준이며 절대경로도 가능합니다. 수정 후 Flipper 창의 별명 / 이미지 새로고침을 누르세요. 잘못된 JSON은 기존 표시를 유지하며 오류를 표시합니다. 없는 이미지는 안내 문구를 표시하고 이동 버튼은 그대로 동작합니다.

이미지는 각 위치에서 빛이 향하는 방향이 보이는 사진 또는 화살표를 그린 광로 그림을 권장합니다. PNG/JPG를 480×200 정도로 준비하면 충분하며 화면에서는 작은 썸네일로 표시합니다. 이미지 클릭으로 장비가 움직이지는 않습니다. 별명/이미지는 표시 전용이고 EA/EC 자동 이동은 별도의 operations/flipper_routes.local.json에서 정합니다.

개인 사진은 `labremote/config/ui/flipper_images.local/`에 두면 Git에서 제외됩니다. 다른 PC에는 flipper_display.local.json과 이미지 폴더를 같은 상대경로로 직접 복사하세요.
