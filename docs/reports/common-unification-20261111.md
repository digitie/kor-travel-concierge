# 공통 관리자 UI 이관 — 2026-11-11

## 정본과 작업 보존

정본은 /home/digitie/dev/common-unification-20261111/kor-travel-concierge이며 브랜치는
agent/codex-common-unification-20261111, 인계 HEAD는 4438328704be15592c47281cd19b525e91567767이다.
기존 clone·브랜치·미커밋 변경을 검토한 뒤 이어서 수정했다. 최초 binary diff와 미추적 파일 목록은
자기 clone의 .git/concierge-resume-initial.patch 및 concierge-resume-initial-untracked.txt에 보존했다.
다른 저장소와 원본 checkout은 수정하지 않았다. push·PR은 부모 통합 이후다.

## 구현한 내용

- 프리미티브는 common의 shadcn/ui Radix export를 소비한다. trigger 합성은 asChild,
  확인 취소는 표준 AlertDialogCancel을 사용한다.
- 관리 표 7개를 공통 VirtualTable로 이관했다: CollectWorkspace의 1회/반복 수집 2개,
  JobsDashboard 1개, JobDetailView의 장소/수집영상 2개, 검수 CandidateTable 1개,
  작업 상세 영상 통계 1개. 후보 선택·부분 선택·행 Enter/Space·액션 예외와 영상 자막 확장행을 보존한다.
- 모바일 Select는 공통 NativeSelect를 사용하며 trigger의 id·라벨·invalid·disabled와
  form·required를 연결한다. 데스크톱은 Radix Select를 사용하고 예약된 빈 값은 sentinel로 변환한다.
- 수집의 RHF+Zod와 공통 LoginForm을 실제 사용한다. 로그인 오류·영상 자막 확장·지도 카메라는
  화면 인스턴스별 Zustand store다. 지도 줌 이벤트만으로 마커·팝업을 다시 그리지 않으며,
  장소/좌표/focusKey 변경 때 카메라 목표를 한 번 고정한다.
- Pretendard Variable은 @kor-travel/tokens/font.css로 로드한다.
- Zod 4의 looseObject/url API, 로그인 HTTP 실패 본문 처리와 서버 redirect 정규화,
  ID 없는 로그·언급·검색 결과 목록의 안정적 key, 명시적 로그 시간대,
  자막 DOM 부착/해제에 묶인 스크롤과 검수 검색어의 원자적 prop 동기화를 보완했다.

## 버전·산출물·검사

부모 versions.json의 axes/frontendPolicy와 생성된 frontend-dependencies 정본의 exact 버전을 따른다. Tailwind/plugin 4.3.5, ESLint 10.14.0,
React Doctor 0.9.22, TypeScript 5.9.3과 Node 22 계열 타입 22.20.5를 사용한다.
TypeScript 7은 openapi-typescript·typescript-eslint peer 범위와 충돌해 정본의 5.9.3을 유지한다.

지도는 GitHub 최신 main 9c46c57181d433c91f7e8837c4e4396204e9b583을 직접 조회해 일치를 확인했다.
부모의 web tsconfig 보완을 포함한 core1.0.0/web1.0.3을 직접 file 의존성으로 고정한다.
현재 설치된 공통 UI0.2.0/tokens0.1.1은 integration-4이며 최종 freeze 전이다.
부모의 다음 integration-6 리뷰용 후보를 요청했으며, 아직 전달되지 않아 그 후보에 대한 최종 검증은 NOT_RUN이다. 해시는
[산출물 원장](../../frontend/common-artifacts.json)과 [출처 기록](../../frontend/vendor/kor-travel-common-provenance.md)을 따른다.
동일 버전 후보를 교체할 때는 네 파일과 원장을 동일 bytes로 복사하고
npm install @kor-travel/ui@file:vendor/kor-travel-ui-0.2.0.tgz @kor-travel/tokens@file:vendor/kor-travel-tokens-0.1.1.tgz로
설치해 이전 integrity를 재사용하지 않게 한다. tokens/radix.css를 로컬 테마 앞에 가져온다.

구 eslint-config-next와 ESLint 10 미지원 eslint-plugin-react 대신 Next plugin·typescript-eslint·
react-hooks·import-x·jsx-a11y-x를 사용한다. shadcn CLI와 불필요한 autoprefixer는 배포 의존성에서 제거했다.
--legacy-peer-deps·--force는 사용하지 않았다.

check:dependencies는 common의 check-dependencies.mjs에 --artifacts common-artifacts.json --source src를
지정한다. 파일·원장·lock 무결성, exact 선언, 금지된 표/overlay 구현과 실제 공통 소비를 검사한다.
CI는 strict peer 설치·guard·lint·Doctor·타입·단위·production build·격리 브라우저를 실행한다.
Doctor CI gate는 --scope full --no-score --no-telemetry --blocking warning으로 전체 검사한다.
광역 규칙 해제·ignore·baseline은 사용하지 않는다. doctor:audit는 --no-respect-inline-disables를 추가한다.
감사 모드는 source lint 주석을 임시 변경하므로 다른 소스 검사/수정과 순차 실행한다.

## Doctor 후속 수정

이전 체크포인트의 26 warning은 완료로 인정하지 않고 모두 재검토했다. API 설정 제목과 source 그룹
선택 옵션의 중복을 공통 소비 코드로 묶고, 상세·수집·스케줄·운영 지표는 요청 상태와 표시 관심사를 분리했다.
RunActionButtons는 중지/재실행/삭제 캐시 갱신 hook과 각 액션 UI를 나눈다.

검수 화면은 진입 컴포넌트, 컨트롤러, 후보 선택/페이지 진행, 삭제/확정/복구, 일괄 작업, 검색·지도,
목록/편집/다이얼로그 모듈로 분리했다. 복구 권한·좌표 검증·로딩 표시의 순수 판정과 view props 투영도
별도 모듈이다. revision·operation ID·scope epoch·세대 ref·undo receipt의 기존 요청 순서와 fencing은 유지한다.
UI 모듈이 컨트롤러 타입을 참조할 때는 type import를 사용한다.

후보 선택·편집 폼·선택 집합은 화면 인스턴스별 Zustand slice를 구독한다. 후보와 폼 초기화는 한 snapshot으로
알리고 함수형 갱신은 직전 draft를 사용한다. session/localStorage 상태는 useSyncExternalStore로 구독하며
초기값을 먼저 덮어쓰지 않고 동일 raw 값의 snapshot을 캐시한다. 저장소 차단·quota 실패에도 현재 입력을 유지한다.
상태 ref와 서버 Query cache는 별도 수명주기를 유지한다.

국소 예외는 DestinationWorkspace의 모바일 deep-link 이동 한 줄뿐이다. 서버에서 알 수 없는 viewport를
확인해 같은 place 파라미터를 데스크톱에서는 모달로, 모바일에서는 기존 상세 route로 여는 계약이다.
해당 줄에 이유와 nextjs-no-client-side-redirect만 명시했다. 실제 Chromium에서 양 경로와 모달 닫기 후
URL 정리를 검증했다. 예외를 무시한 감사에서도 이 한 건만 나오며 다른 진단은 없다.

Vitest 설정은 ESM임을 명시하는 vitest.config.mts로 바꿔 새 Vite loader 경고를 해소했다.
CI의 lint는 --max-warnings 0이며 Doctor는 warning 한 건도 실패시킨다.

## 검증과 잔여 gate

| 검사 | 현재 결과 | 범위 |
| --- | --- | --- |
| npm ci --strict-peer-deps | PASS | 후보4 lock으로 깨끗한 strict peer 설치 재통과; 우회 옵션 없음 |
| check:dependencies | PASS | integration-4 tarball·원장·lock·source 검사 |
| lint/type-check | PASS | ESLint10 경고 0 및 Next route 타입 |
| 단위 | PASS 394/394 | 29파일; 상태 구독6·복구 권한/초안/좌표7 포함 |
| production build | PASS | Doctor 후속 수정의 실제 Next webpack build |
| n150 Chromium | PASS 9/9 | 7개 표·로그인·글꼴·선택·검색·자막·포커스·Select·초안 초기화·반응형 이동·사이드바 복원 |
| Doctor 엄격 gate | PASS, exit 0 | 전체 165파일, error 0/warning 0 |
| doctor:audit | exit 1, 1 warning | 허용한 viewport deep-link 한 줄만 재현 |
| backend/실제 DB/RustFS/provider | NOT_RUN | frontend와 격리 UI 검증 범위 |
| 다음 공통 후보6/최종 singlepack | NOT_RUN | 부모의 파일·원장 전달 뒤 refresh와 최종 앱 gate 필요 |
| 독립 적대 리뷰 2인/원격 CI | NOT_RUN | 부모가 동일 immutable manifest로 통합 실행 |
| push/PR/merge/이미지 배포 | NOT_RUN | 부모 통합·go 이후 |

n150의 전용 임시 디렉터리와 Chromium을 사용하고 loopback reverse tunnel로 이 clone의 production Next에
연결했다. 인증값은 매 실행 무작위 생성해 환경/stdin으로만 전달하며 REST는 브라우저 route fixture로
격리한다. 운영 DB/유료 API를 호출하지 않는다. 9건 모두 retry·skip 없이 통과했다.
새로 추가한 세 시나리오는 후보 A→B→A의 미저장 초안 초기화, 모바일/데스크톱 deep-link 계약,
기존 사이드바 저장값 0/1의 boolean 복원·토글·재로드 구독이다.
상태 구독·권한 판정 단위 검증과 기존 cache/undo/keyboard 검증도 함께 통과했다.

## 부모 go 이후의 이미지 배포 계획

1. 최종 단일pack 원장으로 네 tarball·lock을 다시 정렬하고 모든 필수 검사와 Doctor warning 0,
   동일 commit의 독립 리뷰 2인, 원격 CI, PR merge를 완료한다. 후보 상태에서는 배포하지 않는다.
2. 부모 go 직후 비공개 docs/deploy-runbook.local.md와 최신 Manager 절차를 재확인한다.
   원본 checkout의 비공개 런북 존재와 --no-deps, 비밀번호 hash 비어 있지 않음,
   로그인 POST/Set-Cookie 확인 요구는 민감값 출력 없이 확인했다.
   읽기 전용 재조회에서 현재 UI 이미지 kor-travel-concierge-ui:common-c289b46-16c8461f2fea,
   API/MCP 이미지 kor-travel-concierge-api:common-c289b46-16c8461f2fea,
   code server 이미지 kor-travel-concierge-dagster:common-c289b46-16c8461f2fea를 확인했다.
   API/code server healthy이며 UI는 production 실행 override·bind mount 없음이다. go 직전에 다시 비교한다.
3. 병합 SHA의 git archive를 신규 build context로 만든다. owner-only 운영 source 디렉터리를
   code server build context로 직접 쓰지 않는다. .env·로컬 런북·인증값을 context에 넣지 않는다.
   compose의 실제 UI context는 ./frontend다. frontend/.dockerignore가 .env*·node_modules·.next를 제외한다.
   frontend/Dockerfile의 기본 CMD는 npm run dev지만 운영은 production override로 실행 중임을 확인했다.
   Manager의 production build/start 계약을 보존하고 immutable UI 이미지 태그
   common-ui-<공통SHA12>-<병합SHA12>와 revision label을 사용한다.
4. 기본은 frontend 변경에 필요한 UI 이미지만 새로 빌드한다. Manager 전환이 네 runtime을
   재생성하는 경우 API/MCP/Dagster 기존 태그를 보존하고 UI 태그만 바꾼다.
   공용 plane·PostgreSQL·RustFS 수명주기·schema는 변경하지 않는다.
5. 전환 전 runtime ID·revision·health·기존 이미지 태그와 env 파일 소유권/권한·해시를
   비공개 증거로 보존한다. Manager preflight chain FAIL=0과 global mutation lock을 확인하고
   승인된 compose-boundary activate-concierge --confirm 경로를 사용한다.
   env_file 경로와 secret은 그대로 보존하며 구 이미지 삭제는 하지 않는다.
6. UI 설치 버전/네 산출물 hash·production build·revision, API /health와 code server health,
   Dagster location LOADED를 확인한다. GET /login 200 외에 실제 로그인 POST 200+Set-Cookie,
   UI 비밀번호 hash 길이 0 아님, 잘못된 비밀번호 401, 로그아웃 뒤 원 cookie replay401도 검증한다.
   결과·수집·검수·작업 상세·모바일 Select·자막 확장·지도의 대표 화면 smoke와 기존 전체 live UI를 실행한다.
7. 실패하면 보존한 이전 UI 태그로 공식 경로에서 되돌리고 동일 smoke를 반복한다.
   데이터 삭제·DB downgrade·RustFS 정리·구 scheduler 재활성화는 rollback에 포함하지 않는다.

## 통합 담당자의 다음 작업

1. 다음 리뷰 후보6 원장을 수신하면 네 tarball 해시를 검증하고 vendor·원장을 같은 bytes로 갱신한다.
   UI와 tokens를 명시적 file 설치해 lock integrity를 다시 기록한다. 예전 vendor는 이미 제거했다.
2. 그 후보로 strict peer 설치·guard·lint 경고0·타입·단위·Doctor 전체 warning0·production build·격리 browser를
   최종 재실행한다. 앱의 공통 API monkeypatch는 없으며 현재 추가 common API blocker는 없다.
3. 최종 commit과 단일 원장을 독립 리뷰2인·원격 CI에 전달한다. 이번 로컬 결과가 그 gate를 대신하지 않는다.
4. 통합·리뷰·CI·PR merge와 부모 go 뒤에만 위 순서로 새 이미지를 전환한다.
