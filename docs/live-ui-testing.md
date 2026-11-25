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

## 운영 배포 뒤 자동 확인(n150)

운영 배포 뒤에는 n150에서 `scripts/n150-live-ui-e2e.sh`로 위 읽기 전용 91건을 돌린다. 자격은 root 소유 0600 파일에만 두고, 러너가 그 파일을 root로 읽어 Playwright 컨테이너에 환경변수로만 넘긴다(PinVi admin live e2e의 Docker runner 방식을 따르되, 자격 파일은 사용자 홈이 아니라 root 전용이다). 값은 출력·로그·커밋하지 않는다.

### 인증 구조와 계정

로그인은 단일 관리자 계정이다. UI 컨테이너의 `KTC_ADMIN_USERNAME`과 `KTC_ADMIN_PASSWORD_HASH`(PBKDF2) 한 쌍만 있고, 세션의 `sub`가 이 아이디와 같아야 유효하다. 브라우저 요청은 BFF가 관리자 proxy 비밀로 backend에 넘기므로 로그인한 사람은 모두 관리자 권한이다. DB의 `public_api_keys`는 외부 소비자용 `X-API-Key`이고 화면 로그인에는 쓰이지 않는다. 그래서 e2e 전용 계정을 따로 만드는 정식 경로(CLI·API·화면)는 없고, 자격 파일에는 운영 관리자 아이디·비밀번호를 넣는다. 시험이 운영을 바꾸지 않는 것은 계정 권한이 아니라 시험 fixture가 지킨다 — 모든 `/api/v1` 쓰기와 export를 브라우저에서 막고, 막힌 요청이 하나라도 있으면 그 시험을 실패시킨다. 로그인·로그아웃은 실제 세션과 로그인 감사 이력을 남긴다.

### 소유자가 한 번 할 일 — 자격 파일

n150에서 소유자가 직접 친다. 비밀번호는 `read -rsp`로 받아 화면·명령 이력에 남지 않고(`IFS=`를 붙여 앞뒤 공백도 그대로 받는다), `printf`는 bash 내장이라 프로세스 목록에도 실리지 않는다.

```bash
sudo install -m 600 -o root -g root /dev/null /root/.concierge-e2e.env
IFS= read -rp 'concierge 관리자 아이디: ' ktc_user
IFS= read -rsp 'concierge 관리자 비밀번호(표시되지 않음): ' ktc_pw; echo
IFS= read -rp '대상 URL(공개 https origin, 비우면 loopback UI): ' ktc_url
{
  printf "E2E_ADMIN_USERNAME='%s'\n" "$ktc_user"
  printf "E2E_ADMIN_PASSWORD='%s'\n" "$ktc_pw"
  [ -n "$ktc_url" ] && printf "E2E_BASE_URL=%s\n" "$ktc_url"
} | sudo tee /root/.concierge-e2e.env >/dev/null
unset ktc_user ktc_pw ktc_url
sudo stat -c '%U:%G %a' /root/.concierge-e2e.env   # root:root 600
```

허용 키는 `E2E_ADMIN_USERNAME`·`E2E_ADMIN_PASSWORD`(필수)와 `E2E_BASE_URL`(선택, 기본 `http://127.0.0.1:12605`)뿐이다. 다른 키·중복 키·형식 오류가 있으면 러너는 행 번호만 알리고 멈춘다. 값을 감싼 따옴표 한 쌍은 벗긴다(비밀번호 앞뒤가 따옴표여도 위 명령처럼 한 번 더 감싸 두면 그대로 읽힌다). 관리자 비밀번호를 바꾸면 이 파일도 같은 명령으로 다시 쓴다.

### 실행

검증할 리비전의 소스 트리(git checkout 또는 배포 export)에서 실행한다. 러너가 n150 test gate(`~/gate-slot.sh`, I/O 가드 포함)를 스스로 거치므로 gate로 다시 감싸지 않는다.

```bash
sudo -v                                   # 자격 파일은 sudo -n으로 읽는다
scripts/n150-live-ui-e2e.sh --list        # 수집만(91 tests in 5 files — 아래 범위 표는 90건 시절 기준)
scripts/n150-live-ui-e2e.sh               # 전체 실행 + 요약
scripts/n150-live-ui-e2e.sh --grep '로그인'   # 일부만
```

러너가 지키는 것:

- 자격 파일은 root 소유 일반 파일이고 mode가 0600(또는 0400)이어야 하며, 경로에 심볼릭 링크가 끼지 않고, 담은 디렉터리도 root 소유에 group·other 쓰기가 없어야 한다. 아니면 읽지 않고 멈춘다(경로는 `KTC_LIVE_E2E_CREDENTIALS`로 바꿀 수 있다). 대상 URL은 loopback이 아니면 https여야 한다.
- 시험 전에 사전 로그인(`tests/e2e/live-login-preflight.ts`, globalSetup)을 한 번만 해 보고 세션을 바로 회수한다. 자격이 틀리면(401)·잠겨 있으면(429) 실행 전체를 멈춘다 — 틀린 자격으로 91건이 저마다 실패해 운영 관리자 로그인(10분 5회)을 잠그지 않게 한다. `--list`는 사전 로그인을 하지 않는다.
- `bash -x`로 실행하면 자격을 읽기 전에 거부한다. 값은 docker argv에 싣지 않고 환경변수 이름만 넘긴다 — 다만 실행 중에는 docker 그룹(=root 상당)이 `docker inspect`로 컨테이너 env를 볼 수 있다. Node 내려받기·`npm` 설치 단계와 브라우저 프로세스에는 자격 env를 넘기지 않는다. Playwright 출력·요약에서는 비밀번호 값(URL·base64 인코딩 포함)을 `***`로 가리고, 끝나면 결과 디렉터리의 글 파일(`error-context.md`·`report.json` 등)에서도 지운다. 실패 시 페이지 접근성 스냅샷(`PLAYWRIGHT_NO_COPY_PROMPT=1`)은 끄고(단언 실패가 싣는 스냅샷은 Playwright 1.65에서도 남는다 — 그래서 끝의 결과 파일 비밀값 제거가 최종 방어이고, 실행이 끊겨도 EXIT trap에서 돈다), 로그인 helper는 제출 뒤 비밀번호 칸을 비운다.
- 설정은 `tests/playwright.live-ui.config.ts`로 고정이고 인자는 `--list`·`--grep`·`--grep-invert`·`--max-failures`만 받는다. 쓰기 스펙(`*.write.live.spec.ts`)은 `KTC_LIVE_E2E_WRITE=1`을 줄 때만 수집한다 — 지금은 하나도 없다.
- 공식 Playwright 이미지(`tests/package.json` 버전)에서 `.nvmrc`와 같은 Node를 SHA-256 검증해 쓰고, 컨테이너에는 `tests/`만 싣는다(배포 트리의 `.env`는 보이지 않는다). `npm ci`는 install script 없이 돌고, 같은 저장소 러너가 겹치면 차례로 돈다. docker는 `/usr/bin/docker`를 쓴다.
- live 설정이 수집하는 시험 파일은 모두 운영 write 차단을 건다(`live-ui-fixtures` 또는 `map-loading-recovery.spec.ts`의 같은 규칙 guard) — 러너 계약 시험이 이를 확인한다.
- 끝에 `live_e2e_summary 통과=… 실패=… flaky=… 건너뜀=… 소요=…초`와 실패한 시험의 위치·첫 오류 줄을 낸다. 실패 스크린샷은 `tests/test-results/live-ui/`(0700, 실행자 소유로 되돌림)에 남는다. 종료 코드는 Playwright 것이다.

### 대안 검토 — e2e 전용 비밀번호(제안만, 구현하지 않음)

UI에 `KTC_E2E_USERNAME`·`KTC_E2E_PASSWORD_HASH`를 하나 더 받아 그 세션을 읽기 전용으로 두는 방식을 검토했다. 장점은 자격 파일이 새더라도 관리자 권한이 아니라는 점이다. 그러나 지금 BFF는 로그인한 세션을 모두 관리자 proxy로 backend에 넘기므로, 읽기 전용을 지키려면 세션에 역할을 싣고 BFF가 그 역할의 비-GET과 `/api/v1/admin/*`·export를 막는 인증 경로 변경이 필요하다. 로그인 표면이 둘로 늘고(무차별 대입 표적 추가) 역할 검사 누락이 곧 권한 상승이 된다. 지금 범위는 시험 fixture의 쓰기 차단으로 운영 변경을 막고, 이 변경은 소유자 결정 뒤 별도 작업으로 한다.


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

## 2026-10-08 검증 결과

PR #246의 제품 변경을 운영 UI에 반영했다. 최신 후보와 공개 최종 전체 각각 90건 모두 통과했고 실패·skip·flaky는 0건, 자동 재시도도 0회다. 공개 첫 실행 89건 통과/1건 실패는 설정 GET/렌더 대기 누락이었으며 정확한 GET200·입력 9개·비밀번호 빈 값·프롬프트 경계를 유지하는 동기화 수정 뒤 재검증했다. 초기 baseline·진단·후보 실패도 일지에 보존했다.

두 독립 적대 소스 리뷰 및 공개 동기화 delta 리뷰는 PASS/OPEN0이다. 리뷰의 offline 모의 결과와 작성자의 실제 Chromium 결과를 구분한다. 배포 이후 공개/LAN 인증과 실제 summary 정상 조회를 확인했고 다른 runtime ID는 유지됐다. 구체 결과와 미확정 native 조회 지연은 [작업 일지](journal.md)의 같은 날짜 항목을 참고한다.
