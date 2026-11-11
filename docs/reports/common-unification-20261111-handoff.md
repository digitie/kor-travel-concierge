# Concierge 후보6 최종 로컬 검증 인계

## 검토 대상과 변경

- 저장소/브랜치: kor-travel-concierge / agent/codex-common-unification-20261111
- 직전 기준: 9f496d7fec32dea6c9c405c5324ee16ada1879e1
- 이번 변경: integration-6-review의 UI0.2.0/tokens0.1.1/core1.0.1/web1.0.3 네 종과 원장·lock을 동기화했다.
- 파일명이 유지된 UI/tokens/web도 포함해 네 종 모두 명시적 file 설치했다. 구 core1.0.0은 제거했다.
- 키 없는 지도는 공개 mapStyle을 사용하며 더미 키·VWorld 타일 요청을 없앴다.
- 출처·SHA512·라이선스 정본은 [vendor 기록](../../frontend/vendor/kor-travel-common-provenance.md)과
  [원장](../../frontend/common-artifacts.json)이다. 소스·라이선스 고지는 공통 배포물 그대로 보존한다.

## 최종 실행 결과

| gate | 결과 | 로컬 원문 |
| --- | --- | --- |
| 네 종 설치/strict npm ci | PASS | .git/c6-install.log, c6-ci.log |
| 공통 의존성/소스 guard | PASS | .git/c6-guard.log |
| 최신 로컬 canonical 비교 | PASS | .git/c6-canonical.log |
| lint 경고0 / 타입 | PASS | .git/c6-lint.log, c6-type.log |
| 단위 | 394/394 PASS, 29파일 | .git/c6-unit.log |
| production build | PASS | .git/c6-build.log |
| Doctor 전체 warning gate | 0진단 PASS, 165파일 | .git/c6-doctor.log |
| n150 Chromium | 10/10 PASS, retry/skip0 | .git/c6-browser.log, c6-browser-result.json |

canonical 검사는 로컬 common checkout 5e064808fabd3a54968dd20910eaccd04eba9f38의 검사 코드·frontend-dependencies.json과
부모 artifacts/common-artifacts.json을 명시했다. dependency install의 legacy-peer/force 우회는 없다.
Doctor의 기존 반응형 deep-link 한 줄 국소 예외와 감사1건은 직전 검토 기준과 같고 새 억제는 없다.
브라우저는 실제 production Next와 격리 REST fixture를 연결하며, 키 없는 실제 마커·팝업과 요청0건도 확인했다.

공유 root ENOSPC로 중간 build/로그 저장이 실패해 완료 판정을 유보했다가 공간 확보 후 재검증했다.
브라우저 재검증에는 기존 Playwright/Chromium을 재사용했고 인증 상태·결과만 소유한 /tmp에 저장했다.
원문 로그를 자기 .git에 복사한 뒤 일회성 인증 fixture와 종료된 본인 캐시만 정리했다.
기존 사용자 캐시·다른 저장소·DB/RustFS·운영 runtime은 변경하지 않았다.

## 부모에게 넘기는 항목

1. 이번 커밋은 원리뷰어2인의 재검토 slot에 전달할 수 있다. 로컬 구현/필수 검증 blocker는 없다.
2. 부모 소유 .github/workflows/common-frontend-policy.yml은 그대로 보존하며 이번 커밋에 포함하지 않는다.
   reusable code pin은 5e064808fabd3a54968dd20910eaccd04eba9f38이다. foundation merge 후 원격 CI를 진행한다.
3. 최종 pack refresh·중앙 policy/RC 메타데이터·workflow·PR/CI·리뷰 인계는 부모가 담당한다.
4. push/PR/merge/배포는 미실행이다. 독립2리뷰·CI·merge·부모 go 뒤
   [배포 순서](common-unification-20261111.md)의 태그·secret 보존·로그인/대표화면/health smoke를 수행한다.
