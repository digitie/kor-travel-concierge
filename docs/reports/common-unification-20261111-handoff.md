# Concierge 공통 UI 최종 인계

## 2026-11-12 최우선 현재 상태 — C9 / Draft PR265

- 기준 HEAD: 608d63216c065f87be10130048bb7d41deff00a1; branch: agent/codex-common-unification-20261111.
- 정본: integration-9-review. 부모의 C9 미커밋 vendor·원장·lock·중앙 workflow pin을 보존하고 마무리했다.
- 현재 source/metadata/workflow/docs는 Concierge 담당자 소유다. 이번 단계의 UI 런타임 소스 수정·독립 repack은 없다.
- 중앙 reusable code와 common-ref는 2c1182e765bb2bc53e01e0962cf2a73683891e1d에 정확히 고정했다.
- [Draft PR265](https://github.com/digitie/kor-travel-concierge/pull/265)는 같은 브랜치에서 갱신한다. merge/deploy는 하지 않는다.

### 증거와 최종 gate

| gate | 결과·수용 범위 | 원문 위치 |
| --- | --- | --- |
| C9 vendor/lock/설치 원문 | 로컬·n150 모두 사용5종248파일 일치 | .git/c9-installed-equivalence.json, .git/c9-n150/validation/installed-bytes.json |
| C8→C9 동등성 | UI94+tokens25 중 checker2만 변경, 나머지117파일 동일 | .git/c9-installed-equivalence.json |
| C9 로컬 guard/canonical | PASS, 실제 C9 checker와 canonical 원장 비교 | .git/c9-guard.log, .git/c9-canonical.log |
| C9 n150 fresh strict ci/guard | PASS, legacy-peer/force 없음 | .git/c9-n150/validation/strict-ci.log, guard.log |
| C9 n150 production build | PASS, 현재 C9 설치본으로 새 build | .git/c9-n150/validation/production-build.log |
| C9 n150 Chromium | WSL에 동일 build 제공, 원래 전체10/10 PASS·retry/skip0 | .git/c9-n150/validation/browser.log |
| C8 unit/lint/type/Doctor | 부모 검증 unit394·lint·type·Doctor0 PASS를 위 동등성 근거로 승계 | 부모 validation/kor-travel-concierge-c8-*.log |

첫 격리 snapshot에는 .git 부모가 없어 세션 상태 디렉터리를 생성하지 못했고 브라우저10건이 로그인503으로
실패했다. 같은 build의 HTTP 재현에서 부모 없음503/AUTH_UNAVAILABLE → private 부모 생성 후200/Set-Cookie를
확인했다. fixture 디렉터리만 보완했으며 앱·UI source 수정, 추가 install/build, timeout·retry 완화는 없다.
보완 후 n150에 서버와 브라우저를 함께 둔 실행은 context 준비·로딩 timeout이 있었고 독립 브라우저에서는9/10이었다.
당시 host load14~19에서 같은 C9 build를 WSL에 복사해 서버 부하를 분리했다.
server/static351파일의 SHA256이 원격 build와 모두 같음을 확인했고, 남은 수집→작업 상세 사례는 수정 없이5.9초에 통과했다.
최종10/10은 WSL Linux Next + n150 Chromium으로 원래 전체 suite/config를 그대로 실행한 결과다.
앞선 실패 원문과 원인은 .git/c9-n150/validation/browser-attempt*.log 및 browser-case-*.log에 보존했다.

C6의 strict ci/browser10 증거는 과거 기록이다. 위 C9 strict ci/build/browser는 이번에 n150에서
새로 검증한 별도 결과이며 C6 결과를 대체 재사용하지 않았다. C9가 checker만 바꿨으므로 로컬 전체 gate는
반복하지 않았다. 로컬 root/tmp 공간 제약 때문에 새 설치·build는 여유 있는 n150 디스크의 전용 공간에서
직렬 실행했고, 운영 서비스·다른 사용자 cache를 정리하거나 변경하지 않았다.

현재 사용 산출물·hash·license는 [출처](../../frontend/vendor/kor-travel-common-provenance.md)와
[원장](../../frontend/common-artifacts.json), [검증 요약 JSON](common-unification-20261112-c9-validation.json)을 따른다.
CSSfix4와 VWorld3는 변경하지 않았다. 부모 확인 기준 VWorld PR32/serde PR1은 병합됐고 각각 원장 source와 tree가 같다.

### 실제 잔여 gate와 배포 준비

- 로컬 구현·C9 fresh 설치/build/browser blocker는 없다.
- common PR49는 archive-scanner의 공개 문자열 오탐 처리와 foundation main 정책 병합이 선행되어야 한다.
  따라서 중앙 latest-main canonical CI를 완료로 표시하지 않는다.
- 부모가 소비자 독립2리뷰와 정확 HEAD CI를 조정한다. 그 뒤 부모 go 전까지 merge·이미지 전환을 하지 않는다.
- 비공개 배포 런북을 읽었고 UI의 현재 immutable 태그·build/start override·bind mount0을 읽기 전용으로 확인했다.
  실제 UI context는 ./frontend이며 .dockerignore가 .env*·node_modules·.next를 제외한다.
- 새 이미지는 병합 SHA의 깨끗한 frontend context와 common-ui-<공통SHA12>-<병합SHA12> 태그로 준비한다.
  runtime secret과 env_file을 보존하고 로그인 POST/Set-Cookie·실패 로그인·로그아웃 재사용·대표화면·health를 smoke한다.
  DB/RustFS/API/Dagster 변경은 이번 소비자 범위에 포함하지 않는다.
- 더 자세한 전환·이전 UI 태그 복귀 순서는 [배포 계획](common-unification-20261111.md)의 해당 절을 따른다.
  운영 접속값과 secret은 로그·커밋·PR에 넣지 않는다.

## 이전 검증 기록 — C6

### 검토 대상과 변경

- 저장소/브랜치: kor-travel-concierge / agent/codex-common-unification-20261111
- 직전 기준: 9f496d7fec32dea6c9c405c5324ee16ada1879e1
- 이번 변경: integration-6-review의 UI0.2.0/tokens0.1.1/core1.0.1/web1.0.3 네 종과 원장·lock을 동기화했다.
- 파일명이 유지된 UI/tokens/web도 포함해 네 종 모두 명시적 file 설치했다. 구 core1.0.0은 제거했다.
- 키 없는 지도는 공개 mapStyle을 사용하며 더미 키·VWorld 타일 요청을 없앴다.
- 출처·SHA512·라이선스 정본은 [vendor 기록](../../frontend/vendor/kor-travel-common-provenance.md)과
  [원장](../../frontend/common-artifacts.json)이다. 소스·라이선스 고지는 공통 배포물 그대로 보존한다.

### 최종 실행 결과

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

### 부모에게 넘기는 항목

1. 이번 커밋은 원리뷰어2인의 재검토 slot에 전달할 수 있다. 로컬 구현/필수 검증 blocker는 없다.
2. 부모 소유 .github/workflows/common-frontend-policy.yml은 그대로 보존하며 이번 커밋에 포함하지 않는다.
   reusable code pin은 5e064808fabd3a54968dd20910eaccd04eba9f38이다. foundation merge 후 원격 CI를 진행한다.
3. 최종 pack refresh·중앙 policy/RC 메타데이터·workflow·PR/CI·리뷰 인계는 부모가 담당한다.
4. push/PR/merge/배포는 미실행이다. 독립2리뷰·CI·merge·부모 go 뒤
   [배포 순서](common-unification-20261111.md)의 태그·secret 보존·로그인/대표화면/health smoke를 수행한다.
