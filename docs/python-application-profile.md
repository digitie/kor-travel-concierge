# 실제 공유 Python application 의존성

`backend/application-constraints.txt`는 Common의 유한한 shared catalog를 Concierge의 실제 Python·Dagster 호환 범위로 고정한다. 실제 API/MCP 공용 설치와 CS의 추가 설치가 모두 `Dockerfile.python`에서 이 파일을 `pip -c`로 소비한다. constraints는 설치 요청이 아니며, API에 미사용 Dagster·dev 도구를 추가하거나 옛 Scheduler 서비스를 시작하지 않는다.

정본 값·canonical Git SDK source는 [Common application 규칙](https://github.com/digitie/kor-travel-common/blob/694b814ce625778d31b6aa57b8ae2c8c4f22a752/docs/standards/versions.md#선택-python-application-profile)이 소유하고, 검사 source ref는 `.github/workflows/psycopg-policy.yml`에 고정한다. 프론트엔드 정책·pack·Node 입력과 시스템 패키지 목록은 이 변경에서 바꾸지 않는다. normal Python base 선택은 3.12로 올리며 새 target native 증거가 필요하다.

## 호환 경계

선택 normal Dockerfile은 Python 3.12이며 NumPy/AV/pyproj의 최신 호환 경계를 만족한다. Common SDK의 최소 Python은 바꾸지 않는다. 기존 운영 3.11 receipt를 새 3.12 이미지 증거로 재사용하지 않는다.

Gemini는 유지 중인 REST 게이트웨이 경로를 사용한다. 실제 source에 호출/import가 없는 `google-generativeai` 선언을 제거하므로 genlang의 과거 exact 및 protobuf<6 제약을 새 역할에 강제하지 않는다. 새 provider SDK 프레임워크를 추가하지 않는다. 현재 Dagster family/Common gRPC health와 호환하는 protobuf를 소비 constraints로 고정한다.

MCP 2.3의 `MCPServer`에 도구를 등록하고 host/port/path는 transport 실행 API에 전달한다. 실제 이전 1.30의 read 3개/write 9개 도구 schema와 안정 protocol을 고정해 같은 값을 검증한다. in-process ASGI handshake·목록·읽기 도구와 잘못된 Host 거부를 확인하며 DB/외부 HTTP를 사용하지 않는다.

빌드 도구는 별도 `--python-build-tools` 선택이다. normal pip를 정확 catalog로 bootstrap하고, 이미 설치된 setuptools/wheel만 정렬한다. PEP 517 격리 build에는 같은 `--build-constraint`를 전달한다. runtime에 없는 도구를 추가하지 않는다.

canonical VWorld SDK는 비동기 `VworldClient`를 공개한다. 유지 중인 3개 ETL 파일의 이전 `AsyncVworldClient` import·타입 이름을 이 공개 이름으로 바꿨다. await 호출·좌표 순서·road/parcel 병합·응답 파싱·오류 처리는 그대로이며 실제 SDK와 MockTransport로 정상/무결과/HTTP 오류를 검사한다.

## 검사와 증거

- 기존 source policy job이 실제 소비 constraints와 역할 Python을 검사하고 Docker 설치 연결 시험을 실행한다. 오래된 실제 AnyIO constraint는 실패해야 한다.
- 정상 설치 직후 `pip check`와 `scripts/check_application_install.py`를 유지한다. 기존 필수 API 축은 누락 시 실패하고 나머지 shared 이름은 실제 설치 교집합만 대조한다. 출력의 `python`·`packages`는 Common `--installed-versions` 입력 형식이며 설치하지 않은 catalog 이름을 설치했다고 표시하지 않는다.
- 로컬 실제 사용 requirements metadata 해석·설치/pip check·기존 geocoding/Gemini/Dagster 요약과 새 경계 시험은 소스 수용 증거다. DB·운영 HTTP·생산 배포 증거가 아니다. 전체 Common source 파일의 byte 대조와 normal/native의 기존 provenance 검증을 별도로 유지한다.
- 이전 수용 이미지와 수치 버전이 같더라도 constraints/Git source 입력이 바뀌므로 새 정상 이미지/native와 공식 SDK 적용 증거가 필요하다. 프론트엔드 source tree가 같으면 기존 실제 UI image/source 증거를 그대로 사용하며 label을 새 source로 바꾸지 않는다.


## 조사 범위

정책은 원래 네 uv lock의 105개 이름과 추가 owned-role 49개/필요 동반 배포를 대상으로 한다. 이 목록을 모든 앱의 운영 전이 의존성 전체라고 표시하지 않는다. 역할별 실제 설치 교집합과 의미 있는 소비자 시험을 별도 기록한다.
