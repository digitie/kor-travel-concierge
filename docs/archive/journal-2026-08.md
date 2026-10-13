# JOURNAL — 2026-08 과거 기록

과거 기록 아카이브이며 새 일지는 [현재 일지](../journal.md)에 추가한다.

| 파일 | 기간 | 항목 수 |
| --- | --- | --- |
| [journal-2026-08.md](journal-2026-08.md) | 2026-08-11 ~ 2026-08-31 | 4 |

---

## 2026-08-31: 최신 kor-travel-map admin UI 구조·컴포넌트 정렬

- **기준 확인**: 별도 저장소 `kor-travel-map`의 `origin/main` 최신 커밋
  `2c1cf954`(2026-08-31)를 확인했다. 최신 admin의 `Rail-Workbench`, 그룹형 메뉴, 접힘 Rail,
  header band, `control/panel` 반경, flat card, `StatStrip`, Pretendard, hairline 표면을 기준으로
  삼았다.
- **색상 정책**: 기준 레포의 초록색 값은 가져오지 않았다. Concierge의 기존 보라색
  `#7c3aed`/`#6d28d9`/`#ede9fe` accent와 짙은 보라색 `shell-rail`을 유지하고, 새 구조에서
  필요한 상태 tint·focus·control 경계만 같은 semantic token 계층에 추가했다.
- **구조·컴포넌트**: 실제 Concierge route만 `개요`·`수집 파이프라인`·`검수`·`시스템`으로
  그룹화하고 모바일 가로 메뉴·데스크톱 16rem/4rem 접힘 Rail을 적용했다. `Card`, `SectionCard`,
  `StatStrip`을 추가하고 `Panel`, Button/Input/Select/Tabs/Table/Dialog/AlertDialog/Popover,
  field·badge·checkbox·switch의 공통 recipe를 최신 기준과 같은 밀도로 맞췄다. 결과·수집·검수·
  작업·설정·상태의 주요 외곽 작업면과 알림/표 경계도 flat panel/hairline 언어로 통일했다.
- **인증 화면**: 카드 프레임을 제거한 단일 가운데 로그인 열, 고정 오류 슬롯, 로딩 버튼 라벨 유지,
  footer hairline을 적용했다. 로그인 API와 route 동작은 변경하지 않았다.
- **검증**: frontend `lint`, `type-check`, Vitest **332건**, `next build --webpack`을
  통과했다. n150에서는 UI 컨테이너 인증 환경값 존재, backend LAN `/health` 200,
  공개 `/login` 200, 로그인 POST 200 + Set-Cookie, 잘못된 비밀번호 401을 확인했고,
  live-shell Playwright E2E 4개를 통과했다. 공개 `/health`는 UI 인증 middleware가
  `/login?next=/health`로 redirect하는 경로이므로 backend LAN health를 별도로 확인했다.

## 2026-08-27: 브랜드 accent 보라색 전환과 kor-travel-geo look-and-feel 정렬

- **색상 전환**: 운영 콘솔의 단일 accent brand를 초록(`#1f6b51`)에서 보라(violet-600
  `#7c3aed`/hover violet-700 `#6d28d9`/soft violet-100 `#ede9fe`)로 전환했다. 색 값은
  서비스별 공용 팔레트 테스트셋(첨부 HTML)의 Purple 항목을 그대로 사용했다. 색은
  `frontend/tokens.css`(정본) 한 곳만 편집하면 전 화면에 전파되도록 이미 구성돼 있어,
  다크 사이드바(shell-rail)·다크 모드(현재 미사용, 토글 없음) 변형까지 함께 갱신했다.
- **kor-travel-geo-ui 세부 정렬**: DESIGN-RULES 3/4에 맞춰 카드·다이얼로그·버튼 반경을
  12px→8px(`--ktc-radius`, `tailwind.config.ts`의 `rounded-xl`도 토큰에 매핑), 그림자를
  4~12% 수준의 단일 레이어로 경량화했다. `.ktc-eyebrow`(11px/800/0.11em/brand색 →
  12px/700/0.04em/text-secondary), `Input`/`Textarea` 높이(40px→44px, DESIGN-RULES 5의
  44px touch target)와 반경(6px→8px, `Button`/`Select`와 정렬)을 geo 수치에 맞췄다.
  로그인·오류 패널의 무거운 `shadow-elevated`는 geo의 `.login-panel`/`.app-error-panel`과
  같은 `shadow-card`로 교체했다. `select.tsx`는 coarse-pointer 인식 가변 높이(마우스 32px/
  터치 44px)를 이미 갖춘 의도된 설계라 대상에서 제외했고, UI 구성(레이아웃·컴포넌트 구조)
  자체는 바꾸지 않았다.
- **적대적 리뷰 2인 교차 확인**: 전문 UI 리뷰어 서브에이전트 2명(브랜드 대비/접근성 렌즈,
  완결성/일관성 렌즈)이 독립적으로 검토했다. 두 리뷰어가 공통으로 지적한
  `--shadow-elevated`(전환 후 미사용·`--shadow-modal`과 중복)·`--shadow-button`(tokens.css
  정본을 우회한 하드코딩)·`AppShell.tsx` 로고 타일의 `rounded-[0.65rem]`(8px 체계에서 이탈)을
  수정했다. 한 리뷰어만 발견한 다크 모드 `--ktc-brand-foreground`의 초록 잔존값,
  `frontend/docs/DESIGN-RULES.md` 자체에 남아 있던 구 초록 hex·0.625rem 반경·40px input
  높이 문서 기술도 함께 정정했다. `Input`/`Textarea`의 `rounded-md`(6px)를 `Button`/`Select`/
  geo의 `.field input`과 같은 `rounded-lg`(8px)로 맞췄고, `globals.css` 상단의 (이미 후속
  `@layer base`에 완전히 가려지는) 구 초록 fallback 블록 값도 landmine 방지 차원에서 함께
  갱신했다. `select.tsx` 44px/32px 가변 높이로 인해 일부 화면에서 `Input`(44px)과
  `SelectTrigger`(32px)의 정렬 격차가 넓어진 점은 n150에서 실화면으로 확인 후 필요 시에만
  후속 조치하기로 남겼다. 두 리뷰어 모두 BLOCKER 없음, 병합 승인.
- **검증**: frontend lint·`tsc --noEmit`·Vitest 332건·production build(`next build --webpack`)
  통과. 인증이 필요한 화면(대시보드·검수·다이얼로그)은 로컬에 서명된 세션 쿠키를 재현할 수
  없어 로그인 화면만 로컬 렌더로 확인했고, 인증 화면은 n150 실배포 후 실 로그인으로 라이브
  E2E 확인한다(진행 중, 상세는 후속 기록 참조).

- **Hallmark 재설계**: 운영 화면을 짙은 숲색 전역 내비게이션과 작업면 중심의 카드·상태·표 계층으로
  정리했다. 결과·수집·검수·작업·설정과 상태·API의 현재 정보 구조를 보존하고, 모바일에서는 같은
  항목을 4열 격자로 제공한다. 색상·여백·타이포그래피·상태 토큰은 `frontend/tokens.css`와
  `design.md`에 기록했다.
- **검수 작업면**: T-186으로 분리한 검수 큐·검색·선택·확정 흐름을 유지하면서 데스크톱 3열
  작업면과 좁은 화면의 단일 열 순서로 재구성했다. Google 결과는 검수자가 명시 선택해 저장할 수
  있지만 Gemini 의견 요청·provider 응답 cache·외부 feature export에는 포함하지 않는다.
- **n150 실데이터 검증**: API·UI를 재생성하고 health, 로그인 POST 200+Set-Cookie, 잘못된
  로그인 401, UI 인증 환경값을 확인했다. Ubuntu 26.04의 Playwright Chromium 미지원·시스템
  브라우저 부재 때문에, SSH 터널을 통해 같은 n150 실서비스를 대상으로 Windows fallback
  Playwright를 실행해 UI E2E 4개를 통과시켰다. 데스크톱·모바일 검수 화면도 캡처로 확인했다.
- **추가 검증**: 프런트엔드 타입 검사, Vitest 18개 파일·332개, production build와 Google
  저장·외부 export 차단을 포함한 실제 PostGIS 백엔드 표적 테스트를 통과했다.

## 2026-08-13: T-186 Google 명시 선택 확정 저장 예외

- **사용자 결정 반영**: 검수자가 명시적으로 선택한 Google Places 결과는 `travel_places`와
  `provider_evidence_json.review.resolutions[]`의 확정 provenance에 저장하도록 허용했다. 선택한 hit은
  지도 marker·근접 중복 확인·Gemini 의견 요청과 같은 검수 capability를 쓰며, Web·MCP는 동일한
  `resolve_candidate` 경계를 통과한다.
- **정책 경계**: Google/provider 응답 cache는 deny-by-default를 유지한다. `api_source=google` 장소의
  candidate·mapping은 feature export `PENDING`으로 두고, 기존 ledger는 tombstone으로 회수해 검수 저장이
  외부 feature export로 번지지 않게 했다.
- **검증**: 실제 PostGIS에서 Google 검색·service resolve·REST resolve·외부 export 차단/tombstone을
  검증했다. 상태·캐시·동시성, 키보드·모바일·접근성 두 적대적 리뷰의 최종 delta는
  BLOCKER/MAJOR/MINOR 0건이었다.

## 2026-08-11: 검색어 반복 수집 수정·삭제와 검수 provider/응답성 보완

- **검색어 반복 작업**: 반복 검색어를 수정할 수 있도록 `SourceTargetUpdate.query`와 수집
  수정 다이얼로그를 확장했다. 검색어 변경은 watermark·스캔 실패 상태·실행 횟수를
  초기화하지만, 이미 수집한 동영상·장소·실행 이력은 보존한다. 같은 검색어 중복, 진행 중인
  기존 검색 실행, 공백 검색어는 안전하게 거부한다.
- **경합·감사 일관성**: 최초 one-shot harvest에도 `source_target_id`를 기록하고, 수정·삭제·
  scheduler·`run-now`가 source target 행 잠금을 공유하게 했다. 대상 변경과 감사 로그는 한
  transaction으로 commit하며, 삭제 표식(`scan_interval_minutes=None`) 대상의 stale
  `run-now`는 409으로 거부한다. 반복 상한 도달 후 비활성화된 작업의 기존 수동 실행 계약은
  유지한다.
- **Google Places 수동 확정**: 정책이 확정되지 않은 Google 결과는 검색·선택은 가능하되,
  선택 시 `api_source=manual`로 변환하고 Google 원본 evidence, place ID, 주소를 저장하지
  않는다. Gemini 의견 요청에서도 Google hit을 제외하고 서버도 직접 전송을 필터링한다.
- **검수 속도**: 장소 검색은 Google/Kakao/Naver 호출을 동시에 시작하되 각 provider의 응답
  상한을 3초로 제한해 느린 한 곳이 전체 응답을 막지 않으며, timeout이면 나머지 부분 결과를
  반환한다. 검수 목록의 정확 total은 page query의 window count로 계산해 초기 별도 full scan을
  제거했다.
- **검증**: 프런트 단위 테스트 18개 파일·332개, lint, 타입 검사, production build를 통과했다.
  전용 disposable PostGIS에서 API 59개와 장소 검색·페이지네이션 23개 테스트를 통과시켰다.
  n150 live UI E2E는 4개 통과(로컬 시드 전용 46개 skip)했고, 배포 뒤에도 같은 4개를
  재실행해 통과시켰다.
- **live UI E2E**: 검수 화면의 기본 처리 모드에서 목록 전용 테이블을 기대하던 selector를
  목록/관리 모드 전환 뒤 검증하고, 일괄 선택 상태와 Google Maps Places 표기도 현재 UI와
  일치하도록 고쳤다. 운영 데이터에는 영향을 주지 않는다.
- **n150 prod 배포**: API·scheduler·UI를 분리 재생성했다. 승인 아래 manager의 누락된 UI
  override와 Map migration 환경값을 복구해 UI의 raw env·production start 계약을 되살렸으며,
  API health 200, 로그인 페이지 200, 로그인 POST 200+Set-Cookie, 틀린 비밀번호 401과 UI
  인증 환경값 길이를 확인했다.

---
