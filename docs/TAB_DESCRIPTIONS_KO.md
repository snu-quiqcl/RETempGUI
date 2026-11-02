# 탭 마우스 설명

공통 설정: `labremote/config/ui/tab_descriptions.json` (Git 공유)
PC별 추가/덮어쓰기: `labremote/config/ui/tab_descriptions.local.json` (Git 제외)

```json
{
  "descriptions": {
    "Windfreak": "Windfreak RF 장비 그룹 설명",
    "synthhd_760": "이 장비의 실험 용도를 입력하세요.",
    "Windfreak/synthhd_760": "같은 이름이 여러 곳에 있을 때 부모 탭/장비 이름으로 구분",
    "EA Fluorescence": "EA fluorescence 실험 설명"
  }
}
```

키는 화면의 탭 제목입니다. 대소문자를 구분하지 않으며, 부모 탭/현재 탭 키가 우선합니다.
설정 저장 후 마우스를 탭에서 뺐다가 다시 올리면 반영됩니다. GUI 재시작은 필요 없습니다.
빈 문자열은 설명을 숨깁니다. 미등록 키는 기존 tooltip을 유지합니다.
잘못된 JSON은 로그에 남기고 마지막 정상 설정을 유지하며 장비 동작을 중단하지 않습니다.
새로 검색된 장비 탭 및 별도 상세 창에도 적용됩니다. 상세 창으로 옮겨져 탭 자체가 없는 메뉴 항목은 대상이 아닙니다.
