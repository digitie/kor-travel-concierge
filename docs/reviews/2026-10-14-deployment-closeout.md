# 2026-10-14 배포·교차 저장소 병합 기록

## Concierge UI 운영 반영

인증 감사의 정지 대기를 격리한 [PR #254](https://github.com/digitie/kor-travel-concierge/pull/254)와 번들 간 로그아웃 폐기·상태 오류503을 보강한 [PR #256](https://github.com/digitie/kor-travel-concierge/pull/256)이 main에 병합됐다. #256 병합 commit은 e9864d8015602b48be73a39590cf9d9d40e3d31f다. 새 immutable UI의 실제 공개 UI **91 PASS / 실패0·skip0·retry0·flaky0**, frontend376/lint/type/production build 및 소유 backend의 실제 Next compiled HTTP12를 확인했다. 독립 source/controller·최종 기록 리뷰2명의 발견을 수정해 OPEN0을 확인했다.

image sha256:98217aee96e957cf99a4d6a0c7c983c6c0f597f8c5bf31a854859831efe937a9, container 18e5b6e57c194e0e0e212b94735d57fe6beba47be73e136d7d4f7622fb8ba151, 이미지 소스 bb10ceda8fc72a1d5eb628fe41d72fbfa6a9b5b4다. 추적 frontend144파일·compiled 감사/세션 marker·LAN/public JavaScript asset11을 대조했고, 실제 LAN/public login200·오류401·logout200·보관한 원cookie replay401을 확인했다. 테스트 후 운영 소스7파일·UI identity/restart/OOM·다른6서비스 ID/image/env·Manager 입력 불변을 다시 확인했다. 다른 앱/backend/schema 및 공용 daemon은 이번 UI 배포에서 재생성하지 않았다.

최초 배포는300초 안에 빌드가 완료되지 않아 복구를 시작했고 기존 alias 복원 명령이 timeout됐다. 원 영수증 RECOVERY_REQUIRED/태그 UNKNOWN과 CLI PID 부재를 보존하며 ACK·롤백 성공을 소급하지 않는다. 이번 배포는 검증한 immutable image로 직접 고정하고 canonical alias를 바꾸지 않았다. 다음 UI 배포에도 검증한 pinned projection/image 선택을 유지해야 하며 기본 alias만으로 같은 이미지라는 보장은 없다. 첫 image load 응답 UNKNOWN도 서버의 원 영수증을 재관찰하고 중복 launch 없이 Loaded image ACK·PID 부재·image/source 일치를 확보해 구분했다.

## 실제 공개 UI 검증 범위와 실패 이력

- 최신91 실행 시작 2026-10-14T05:51:36.161Z, 약222초. WSL Linux Chromium software WebGL을 사용했다. n150의 이번 preflight timeout 및 WebGL2 미지원은 PASS로 바꾸지 않는다.
- 실제 인증·deep link·로그아웃 원cookie 재사용 거절·메뉴·모바일 viewport·폼·장소/검수·native Dagster 조회와 지도 PNG tile/canvas/marker 준비를 확인했다. 도메인 데이터 쓰기와 비용이 큰 provider 호출은 막았고 실제 인증 감사 쓰기는 발생할 수 있다.
- 로그인/Dagster/목록/지도 지연·오류·재시도 모형은 browser fault 또는 fixture 여부를 구분한다. 운영 Dagster job 강제 실패·provider 장애·Odroid 복구 시험으로 확대하지 않는다.
- 최초 새 UI의90 PASS 뒤 별도 실제HTTP에서 원cookie replay200 RED를 발견했다. R4 이미지의 전체 UI는90PASS/1FAIL(390px 메뉴401 이후 timeout)이었고, R5 unavailable503/invalid401 분리 후 이번91을 모두 통과했다. 초기 실패 원문을 유지하고 R4 401의 정확한 원인을 cap으로 확정하지 않는다.
- 상태 helper 호출자 deadline2초와 고정 bundle32개 입장 상한은 syscall 취소·전체 인증요청2초·총 RSS/디스크 감소 보장이 아니다. 지원 범위는 같은 단일 Linux UI 컨테이너이며 nonce 보존 후 marker 부분 유실·분산 replica는 보장하지 않는다.
- 저장소의 GitHub workflow가 없어 자동 CI 결과는 미제공이다. 실제 native/build/live 및 리뷰 결과를 그와 구분한다.

## Odroid 장애에 따른 이번 병합 예외

사용자가 Odroid 장애를 보고했고, Geo·Weather·Transport의 live E2E/UI E2E를 실행할 수 없음을 명시한 뒤 이번 PR들을 병합하도록 승인했다. 해당 시험 상태는 **NOT_RUN — Odroid 장애**이며 PASS가 아니다. 이 승인은 이번 병합의 예외이고 이후 운영 배포·복구 검증을 완료한 것으로 취급하지 않는다.

| 저장소 | 병합 PR | 병합 commit | 검증 상태 |
| --- | --- | --- | --- |
| Weather | [#84](https://github.com/digitie/kor-travel-weather/pull/84) | `8f52bff56d3f26d0fc797f0f13d45c4d371c71d3` | 코드·회귀·CI·독립 리뷰 통과, live E2E NOT_RUN |
| Geo | [#574](https://github.com/digitie/kor-travel-geo/pull/574) | `7d3217c2095f9fe834f55011fd0d22e4a272b3f5` | 코드·회귀·CI·독립 리뷰 통과, live E2E NOT_RUN |
| Transport | [#78](https://github.com/digitie/kor-travel-transport/pull/78) | `40f63498d653b456ba8fdf30826923129bc80d77` | 코드·회귀·CI·독립 리뷰 통과, live E2E NOT_RUN |

각 PR은 먼저 초안으로 만들었고 기능 단위 커밋을 원격에 올렸다. 두 명의 독립 코드 리뷰 및 마지막 예외 문서 리뷰의 발견을 반영했다. Geo의 오래된 preview 성공값 제거·응답 상태 확인과 Weather의 응답별 바이트 상한 표현 수정은 초기 발견을 보존한 뒤 수정했다. Transport의 마지막 backend CI까지 완료한 뒤 병합했다. GitHub의 live-e2e SKIPPED는 실제 운영 시험 통과를 의미하지 않는다.

## 남은 운영 조건

- Odroid 복구 뒤 세 저장소의 실제 API·native Dagster·UI·장애/중단/복구 검증을 수행한다. 재시작·장기 정지·메모리 최대값을 이번 코드 검사 결과로 대체하지 않는다.
- Concierge T-199 단독 backend/schema 전환은 ADR-49가 병렬 배포를 허용하므로 fresh backup/drain·현재 UI 보존·새 제어 리뷰를 갖춰 별도 진행한다. T-200 배포·첫 운영 refresh는 Geo token/backfill·Map 토큰 계약·Manager lane 등의 선행을 확인하기 전 완료로 표시하지 않는다.
- T-202b의 Geo URL 전환은 하위 서비스 복구·전환 순서 조건을 충족한 뒤 수행한다. 이번 UI 배포 승인으로 앞당기지 않는다.

운영 비밀·원문 로그·주소·계정·비밀번호·세션 cookie는 이 공개 기록에 포함하지 않는다.
