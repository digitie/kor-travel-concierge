# 운영 UI E2E 실행 가이드

운영 화면은 N150 Linux의 실제 Chromium으로 확인한다. `tests/playwright.live-ui.config.ts`는 공개 URL과 비공개 관리자 환경변수를 명시해야 실행되며 seed, 웹 서버 자동 기동, 기본 운영 주소가 없다. 별도 후보 UI는 같은 운영 조회 API를 사용하되 loopback에서만 접속한다.

## 실행

관리자 자격과 대상 URL은 gitignore된 로컬 런북에서 환경변수로 주입한다. 실제 값을 명령 이력·커밋·보고서 공유본에 쓰지 않는다.

```bash
cd tests
npm ci
npx playwright install chromium
# 비공개 환경에서 E2E_BASE_URL, E2E_ADMIN_USERNAME, E2E_ADMIN_PASSWORD를 주입한 뒤 실행
KTC_LIVE_E2E=1 npm run test:live-ui
```

기존 기본 config는 seed 또는 변경을 수행하는 시험을 포함하므로 운영 조회 검증에는 위 전용 명령만 사용한다. 작업자는 1개, 자동 재시도는 0회다. 실패를 먼저 기록하고 원인·수정·회복 근거가 생기면 새 실행 결과를 별도로 보존한다. trace는 끄고 실패 스크린샷·JSON·관측 attachment를 gitignore된 `tests/test-results/live-ui`에 보관한다. 운영 데이터가 포함될 수 있으므로 원문을 PR에 올리지 않는다.

## 90개 시험 범위

| 영역 | 건수 | 주요 검증 |
| --- | ---: | --- |
| 로그인·메뉴 | 21 | 무인증 deep link, 필수 입력, 잘못된 비밀번호와 회복, HTTP 오류·중복 제출, 외부 next 차단, logout·다른 탭, 키보드·저장된 메뉴, 320/390/768/1440 화면과 모바일 메뉴 |
| 폼·작업 액션 | 22 | 수집 자동 판별·경계·반복, 설정 키 비노출·프롬프트 경계·저장 실패·폐기 취소, 공급 GET, 작업 중지/삭제/재시작 취소·실패·등록 중 중복·기존 재시작·중지 접수 |
| 운영·Dagster | 19 | 실제 code location/run 조회·선택·로그 링크, 첫 조회/권한/잘못된 payload 오류와 회복, 선택 제거·maintenance 정보, 화면 이탈 signal 취소, 실제 작업 필터·부분 조회 오류·없는 상세·metrics 회복 |
| 장소·검수 | 22 | 행/마커 선택·키보드, 검색·정렬·export cart, desktop/mobile 상세, 목록 오류·빈 결과, 후보 선택·도움말·검색 유지·재조회, 실제 다음 페이지·중복 요청 차단, 입력 경계·synthetic IME·응답 순서, 후보 상세 재시도·자막 탭·빈 자막·목록 밖 deep link |
| 지도 복구 | 6 | 실제 desktop/mobile PNG 타일·마커, 지연 뒤 지도 단독 재시도·선택 보존, WebGL 실패 회복, context 해제 미확인 시 추가 생성 차단 |

넓이가 다른 메뉴 시험 각각은 8개 화면을 방문하지만 건수는 1개로 센다. 실제 장소 2개 이상, 검수 후보 2개 이상, 다음 페이지, source video, 최근 native 실행과 로그인 기록을 요구한다. 데이터가 부족하면 조용히 skip하거나 빈 화면을 성공으로 처리하지 않는다.

## 실제 조회와 장애 주입의 구분

`live-read`는 실제 로그인·운영 BFF/API·저장된 데이터 조회다. `browser-fault`는 실제 UI에서 Playwright route로 응답을 보류하거나 오류/fixture를 주입한 시험이다. provider 검색에는 별도 `browser-provider-fixture` 관측을 남긴다. 지도 정상 시험은 실제 PNG를 확인한다.

공통 fixture는 운영 domain write와 export 다운로드를 차단하고 예상 밖 전송을 시험 실패로 기록한다. UI 액션 시험은 정확한 endpoint를 브라우저에서 처리한다. 확인창 취소는 운영 변경 요청이 없어야 한다. provider 장소 검색·AI 의견·카테고리 매칭은 브라우저 fixture이며 유료 처리 품질을 검증한 것이 아니다. 로그인/logout은 실제 세션을 만들고 종료하며 로그인 감사 이력은 남는다.

모든 공통 시험은 브라우저 런타임 오류와 예상 밖 API/JS/CSS/font 실패를 기록한다. 오류는 해당 화면의 패널에 범위를 좁혀 확인하고 회복은 실제 HTTP200과 내용까지 검증한다. Dagster의 손상된 HTTP200은 정상 snapshot을 교체해서는 안 되며 401/403은 민감 선택을 제거한다. 이탈 시험은 하니스 정리 전에 제품 fetch signal의 abort를 확인한다. 이는 서버 GraphQL 실행 취소 보장이 아니다.

## 결과 해석과 미검증 범위

운영 공개 전체 실행 결과는 작업 일지에 기록한다. 첫 실패·진단·수정 후보·공개 실행을 별도 결과로 남겨 최초 장애를 통과로 덮지 않는다. 운영 요약이 degraded라면 실제 native 정상 조회·수동 복구 시험이 실패해야 한다.

현재 실행 브라우저는 Chromium이다. 해당 Linux 배포판의 Firefox 설치 지원 제약으로 다른 브라우저 실행은 하지 않았다. 실제 작업 강제 종료/timeout/cancel·복구 seed, domain 변경, provider 수집/전사/AI 평가, GPU/heap 최대 사용량과 장기 부하 시험은 이 UI suite의 통과 범위에 포함하지 않는다. 기존 map 6개는 별도 spec의 자체 fence와 관측을 사용한다.
