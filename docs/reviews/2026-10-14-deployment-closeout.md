# 2026-10-14 배포·교차 저장소 병합 기록

## 현재 상태

Concierge PR #254의 인증 감사 대기 상한 소스는 main에 병합됐다. 운영 UI 교체·실제 인증·새 이미지의 UI E2E는 진행 중이며, 이 초안 기록은 그 완료를 주장하지 않는다.

운영 배포 제어기는 별도 독립 적대 리뷰 두 명의 실패 경로 검토를 받는다. 초기 발견과 수정 후 판정을 구분하고, Docker 명령의 시간 초과를 작업 종료로 간주하지 않는다. 기존 원본 저장소의 미커밋 변경과 다른 작업자의 컨테이너를 덮지 않는다.

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
- Concierge T-199/T-200의 backend 전환과 첫 운영 refresh run은 별도다. Geo token 배포/backfill, Map의 토큰 계약 배포, Manager lane 반영 및 native drain/백업 조건을 확인하기 전 완료로 표시하지 않는다.
- T-202b의 Geo URL 전환은 하위 서비스 복구·전환 순서 조건을 충족한 뒤 수행한다. 이번 UI 배포 승인으로 앞당기지 않는다.

운영 비밀·원문 로그·주소·계정·비밀번호·세션 cookie는 이 공개 기록에 포함하지 않는다.
