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

부모 version-targets.json의 exact 버전을 따른다. Tailwind/plugin 4.3.5, ESLint 10.14.0,
React Doctor 0.9.22, TypeScript 5.9.3과 Node 22 계열 타입 22.20.5를 사용한다.
TypeScript 7은 openapi-typescript·typescript-eslint peer 범위와 충돌해 정본의 5.9.3을 유지한다.

지도는 GitHub 최신 main 9c46c57181d433c91f7e8837c4e4396204e9b583을 직접 조회해 일치를 확인했다.
부모의 web tsconfig 보완을 포함한 core1.0.0/web1.0.3을 직접 file 의존성으로 고정한다.
공통 UI0.2.0/tokens0.1.1은 후보3이며 최종 freeze 전이다. 해시는
[산출물 원장](../../frontend/common-artifacts.json)과 [출처 기록](../../frontend/vendor/kor-travel-common-provenance.md)을 따른다.
동일 버전 후보를 교체할 때는 npm install @kor-travel/ui@file:vendor/kor-travel-ui-0.2.0.tgz로
설치해 이전 integrity를 재사용하지 않게 한다.

구 eslint-config-next와 ESLint 10 미지원 eslint-plugin-react 대신 Next plugin·typescript-eslint·
react-hooks·import-x·jsx-a11y-x를 사용한다. shadcn CLI와 불필요한 autoprefixer는 배포 의존성에서 제거했다.
--legacy-peer-deps·--force는 사용하지 않았다.

check:dependencies는 common의 check-dependencies.mjs에 --artifacts common-artifacts.json --source src를
지정한다. 파일·원장·lock 무결성, exact 선언, 금지된 표/overlay 구현과 실제 공통 소비를 검사한다.
CI는 strict peer 설치·guard·lint·Doctor·타입·단위·production build·격리 브라우저를 실행한다.
Doctor는 --scope full --no-score --no-telemetry --no-respect-inline-disables --blocking warning을 사용한다.
감사 모드는 source lint 주석을 임시 변경하므로 다른 소스 검사/수정과 병렬 실행하지 않는다.

## 검증과 잔여 gate

| 검사 | 현재 결과 | 범위 |
| --- | --- | --- |
| npm ci --strict-peer-deps | PASS | 우회 옵션 없는 깨끗한 설치; 이후 후보3 명시적 재설치 |
| check:dependencies | PASS | 후보3 tarball·원장·lock·source 검사 |
| lint/type-check | PASS | ESLint 10 및 Next route 타입 |
| 단위 | PASS 381/381 | 기존 376 + 목록 key 2 + 지도 카메라 3 |
| production build | PASS | 후보3의 실제 Next webpack build |
| n150 Chromium | PASS 6/6 | 7개 표·로그인·글꼴·검수 선택/키보드/검색·자막·확인창·Select |
| Doctor 엄격 gate | FAIL, exit 1 | 최초 47 → 최종 26 warning, error 0; 135개 파일 전체 검사 |
| backend/실제 DB/RustFS/provider | NOT_RUN | 이번 변경은 frontend와 격리 UI 검증 범위 |
| 최종 singlepack 정렬 | NOT_RUN | 부모의 freeze 원장 수신 필요 |
| 독립 적대 리뷰 2인/원격 CI | NOT_RUN | 부모가 동일 immutable manifest로 통합 실행 |
| push/PR/merge/이미지 배포 | NOT_RUN | 부모 통합·go 이후 |

Doctor 잔여는 warning을 숨기거나 baseline/ignore로 우회하지 않는다. 큰 함수·대형 컴포넌트와
공급 패널/그룹 옵션 JSX 중복, 화면 폭에 따라 모바일 상세 route 또는 데스크톱 modal을 선택하는
초기 deep-link redirect를 계속 추적한다. 최종 26건은 복잡한 함수 14·대형 컴포넌트 9·JSX 중복 2·반응형 초기 redirect 1이다.
검수 workflow의 fencing/IME/undo 정책을 대규모 기계적 분할로 바꾸지 않는다.

기준선 추가 검증: 인계 HEAD 4438328704be15592c47281cd19b525e91567767의 frontend 소스를
별도 임시 스냅샷으로 추출하고 현재 package.json의 exact 의존성/같은 설치본을 연결해 동일한 전체
Doctor 감사를 실행했다. 기준선은 130개 파일 완전 검사에서 error 0/warning 49였다.
현재 후보의 26건은 모두 기준선에도 존재하는 파일·규칙 진단이며 신규 진단은 없다.
이 비교는 잔여 gate의 면제나 baseline 필터 적용이 아니다. 현재 CI의 엄격 실패는 그대로 유지한다.


n150 브라우저는 그 호스트의 전용 임시 테스트 디렉터리와 Chromium에서 실행하고,
loopback reverse tunnel로 이 clone의 production Next에 연결했다. 인증값은 매 실행 무작위 생성해
환경/stdin으로만 전달한다. REST는 브라우저 route fixture로 격리해 운영 DB/유료 API를 호출하지 않는다.
운영 UI와 분리된 검증이며, 기존 공개 운영 UI 성공을 이번 후보의 성공으로 재사용하지 않는다.
초기 3/5·후속 5/6 실패는 endpoint/URL/초기 처리 모드에 대한 fixture 가정 오류였고,
최종 6/6은 제품 기본 모드를 실제 버튼으로 바꾼 뒤 검증했다. 새 타이밍 재시도나 skip은 없다.


## 부모 go 이후의 이미지 배포 계획

1. 최종 단일pack 원장으로 네 tarball·lock을 다시 정렬하고 모든 필수 검사와 Doctor warning 0,
   동일 commit의 독립 리뷰 2인, 원격 CI, PR merge를 완료한다. 후보 상태에서는 배포하지 않는다.
2. 부모 go 직후 비공개 docs/deploy-runbook.local.md와 최신 Manager 절차를 재확인한다.
   원본 checkout의 비공개 런북 존재와 --no-deps, 비밀번호 hash 비어 있지 않음,
   로그인 POST/Set-Cookie 확인 요구는 민감값 출력 없이 확인했다.
   실제 운영 이미지 tag/실행 명령의 읽기 전용 조회는 지연되어 확정하지 못했으므로 전환 전에 재조회한다.
3. 병합 SHA의 git archive를 신규 build context로 만든다. owner-only 운영 source 디렉터리를
   code server build context로 직접 쓰지 않는다. .env·로컬 런북·인증값을 context에 넣지 않는다.
   frontend/Dockerfile은 기본 npm run dev 이미지이므로 Manager의 실제 production build/start 계약을
   그대로 확인하고 immutable UI 이미지 태그 common-ui-<공통SHA12>-<병합SHA12>와 revision label을 사용한다.
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

## 재개 시 우선 작업

1. 부모가 새 최종 원장을 알리면 파일 해시를 검증한 뒤 네 tarball과 원장을 복사하고
   명시적 file 설치로 lock을 갱신한다. 현재 후보3과 이후 후보를 섞지 않는다.
2. Doctor 잔여를 진단 위치별로 수정하고 엄격 gate를 다시 실행한다.
   복잡한 함수 14개: AppShell, CandidateDetailView, CollectWorkspace, DestinationList,
   JobDetailView, JobStatusLink, JobsDashboard, PlaceDetailView, RecurringEditDialog,
   ReviewBulkPanel, RunActionButtons, SettingsPanel, StatusDashboard, ReviewWorkspace.
   대형 컴포넌트 9개: CandidateDetailView, DestinationWorkspace, DestinationList, HarvestConsole,
   PlaceDetailView, RecurringEditDialog, ReviewBulkPanel, SettingsPanel, ReviewWorkspace.
   JSX 중복 2개는 공급 패널 제목과 결과/검수 그룹 선택 옵션이다.
   초기 redirect는 DestinationWorkspace의 화면 폭에 따른 deep-link 처리다.
3. 이미 통과한 검증의 명령은 frontend에서 npm run check:dependencies, npm run lint,
   npm run type-check, npm test, npm run build다. tests에서 npm run test:common-ui로
   격리된 production 브라우저 검증을 재현한다. CI에도 같은 단계가 연결되어 있다.
4. Doctor 수정과 새 공통 후보로 영향받는 검증만 다시 실행하고, 새 commit의 독립 리뷰·원격 CI·머지로
   진행한다. 모든 gate 성공과 부모 go 전에는 이미지 재생성이나 운영 변경을 실행하지 않는다.
