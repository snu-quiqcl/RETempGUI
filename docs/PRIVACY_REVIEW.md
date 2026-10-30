# 로컬 장비 설정 분리 검토

2026-10-30. 현재 RETempUI checkout의 IP와 모터 시리얼을 별도 로컬 파일로 이전했습니다. 기존 값은 보존하고 Git 추적 소스에는 loopback/예제 값만 남깁니다. 외부 코드 작성자·저작권 표기는 유지합니다.

- 새 로컬 설정 테스트 7개: 파일 없음, 잘못된 JSON/설정, BOM, 저장된 GUI 설정과 우선순위, 모터 정책 보존과 operation snapshot, 시리얼 검증과 명시적 override.
- 기존 테스트 105개: 모터 QCoDeS 15, architecture 19, review regressions 32, runtime 19, workflow editor 11, CCD 9.
- 합계 112개 테스트 통과. Dummy CCD GUI에서 휠/가운데 드래그 확대, 라이브 확대 유지, 숨긴 탭 이온 대기, 종료 검사 통과.
- 최초 CCD 저장 테스트는 샌드박스 임시 디렉터리 접근 거부, GUI는 프로세스 종료 오류가 발생했습니다. 같은 코드를 권한 제한 밖에서 다시 실행해 CCD 9개 및 GUI 검사가 통과했습니다.
- 실제 장비에는 연결하지 않았습니다. 새 모터 드라이버를 서버에 배포할 때 serials.local.json을 함께 복사해야 합니다.

전달 파일과 적용 순서는 [로컬 설정 안내](LOCAL_SETUP_KO.md)를 참고하세요. GitHub Desktop에서 commit 전 `python check_public_files.py`로 현재 업로드 후보를 검사할 수 있습니다. 검사와 .gitignore는 모든 개인정보 유출을 방지하는 보증이 아닙니다.

Git 기록 재작성·commit·push·저장소 삭제는 수행하지 않았습니다. 이전 커밋의 IP·시리얼·이메일은 별도 기록 정리가 필요합니다. `release_manifest.json`은 이번 변경 후 공개 파일의 해시로 갱신하며 로컬 비공개 파일을 포함하지 않습니다.

> 이후 배포 정책 변경: `tests/`와 `server_deploy_latest/`는 로컬에만 보존하며 Git에서 제외합니다. 위 테스트 결과는 당시 로컬 지원 폴더를 포함한 검증 기록입니다. 새 clone에서의 검증 범위는 현재 README를 따릅니다.
