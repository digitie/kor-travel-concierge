# 외부 provider 정책·데이터 권리 매트릭스 (Phase -1, T-158)

> **이 문서는 법률 자문이 아니다.** 공식 정책 문서와 현재 기술 흐름의 충돌 가능성을
> 릴리스 게이트(G10)로 명시하기 위한 **운영 검토**다. 최종 판단이 필요한 항목은
> "결정 필요 항목"에 모아 사용자 결정을 기다린다.
>
> 확인일: **2026-07-13** / 작성: T-158 (로드맵 PR-29, §10 B4)

## 0. Release gate 선언

이 문서의 "결정 필요 항목"이 결정되기 전에는 다음을 **배포하지 않는다**:

- **T-169** (whisper 정책·재전사 확대) — YouTube 오디오 다운로드 경로 확대
- **T-173** (프레임 OCR/vision 실험) — YouTube 프레임 취득 확대
- **제한 provider 결과의 영구 저장 확대** — Google Places(place ID 제외)·Naver
  (NCP Maps / Developers Local Search)·Kakao Local(사전 승낙 미확인 필드)·VWorld
  결과의 신규 영구 저장 표면

보안·queue·일반 UX 작업은 병행할 수 있다. **기존 RustFS 객체 삭제는 하지 않는다**
(사용자 결정·ADR 필요 — §5 참고). production kill switch는 §4 참고.

**해소된 게이트 항목**: Google Places 결과의 VWorld 지도 **표시** 형태는 사용자
결정(2026-07-13)으로 **현행 유지가 승인**되어 gate 대상이 아니다 — 인지된 정책
리스크로 기록을 보존한다(§3 C-3, §7-2). Google 결과의 **저장** 차단(T-174)은 별개로
유지된다.

## 1. Provider 정책 매트릭스

표기: ✅ 허용 / ❌ 금지 / ⚠️ 조건부 / ❓ 미확인·확인 필요. 각 셀의 근거는 §2.

| 항목 | YouTube Data API | Google Places | Naver — NCP Maps Geocoding | Naver — Developers Local Search | Kakao Local | VWorld |
|---|---|---|---|---|---|---|
| **표시** | ✅ metadata 표시 허용(브랜딩 규정 준수, III.F) | ✅ 지도 없이 표시 허용(ST §14.1) + attribution | ⚠️ 자기 서비스에서 결과 수신 **즉시 1회 사용**만(제7조⑪) | ⚠️ 검색결과 **독립 노출**, 삽입·왜곡·수정·변조 금지(특약 2.1) | ⚠️ 서비스 내 사용(명시 허용이 아닌 금지 조항 부재의 반대해석)[^kakao] | ✅ API 목적 내 사용(실시간) |
| **지도 표시** | ❓ 지도 관련 별도 조항 미확인 | ❌ **비-Google 지도(VWorld 포함) 표시 금지**(ST §14.2) | ❓ 지도 종류 제한 조항 미확인(Maps 사용 가이드 준수 의무, 제7조⑦) | ❓ 명시 조항 미확인(왜곡 금지 원칙 적용) | ❓ 운영정책에 지도 제한 조항 미확인 | ✅ VWorld 지도 자체가 표시 수단 |
| **영구 저장** | ❌ audiovisual content 저장은 **사전 서면 승인** 필요(III.E.1); metadata는 30일 규칙(III.E.4) | ❌ 금지. **예외: place ID는 무기한 저장 가능**(정책 페이지) | ❌ 별도 저장·**DB화·재사용 엄격 금지**(제7조⑨·⑪) | ❌ 무단 복제·저장(캐시 포함)·가공 금지, "지역정보 수집→별도 DB 관리" 명시 금지(7.3.③) | ⚠️ 사전 승낙 없는 복사·복제·타인 제공 금지(제5조) — 영구 저장 허용 필드 ❓미확인 | ❌ "별도의 저장장치나 데이터베이스에 저장할 수 없습니다"(지오코더 가이드) |
| **임시 cache** | ⚠️ API Data 30일 이내 저장 후 삭제/refresh(III.E.4) — 무기한 예외는 Authorized Data 한정, API key 수집(Non-Authorized)에는 **적용 불가** | ⚠️ lat/lng **30일** 임시 캐시 후 삭제(ST §14.3) | ❌ 문면상 불허(즉시 1회 사용, 제7조⑪) — 계정별 제품 약관 확인 전 **기본 off** | ❌ 문면상 캐시 포함 금지(7.3.③) — UX 예외 조항 없음 | ⚠️ UX 개선 목적 cache는 금지 대상에서 제외(제5조 반대해석)[^kakao] + 최신 데이터 유지 의무 | ❌ 문면상 불허(실시간 사용) |
| **attribution 의무** | ✅ YouTube가 출처임을 표시(III.F.2 브랜딩) | ✅ 지도 없이 표시 시 **Google 로고/"Google Maps" 텍스트**(정책 페이지) | ⚠️ 회사 로고·지정 표시 **게재 요청 시 준수**(제7조⑩) | ⚠️ 네이버 BI 가이드 준수(7.3.⑨) — 세부 ❓미확인 | ❓ 운영정책에 명시 attribution 조항 없음 | ❓ 이용약관 전문 미확보 |
| **외부 export** | ❌ Authorized Data는 승인한 사용자 외 접근 불가(III.E.3 — Authorized Data Usage); 파생 POI의 지위는 ❓검토 필요 | ❌ GMP Terms of Service **§3.2.3(a) "No Scraping"·(b) "No Caching"** — Google Maps Content의 대량 취득·캐싱/저장·export 일반 제한 | ❌ 제3자 제공 금지(제7조⑨), API/SDK 재판매 금지(제7조⑫) | ❌ 제3자 제공·재제공 금지(7.3.③·⑥) | ❌ 사전 승낙 없는 타인 제공 금지(제5조) | ❓ 미확인 |
| **허용 TTL** | 30일(metadata refresh/delete, III.E.4) | 30일(lat/lng), place ID는 무기한 | 0 (즉시 사용) — 문면 | 0 — 문면 | 명시 TTL 없음 — "최신 유지" 의무만 | 0 (실시간) — 문면 |
| **약관 버전·확인일** | Developer Policies, Last updated **2026-06-24 UTC** / 확인 2026-07-13 | 정책 페이지 Last updated **2026-07-10 UTC**; Service Specific Terms Last modified **2026-06-10** / 확인 2026-07-13 | Maps 서비스 이용약관 **v0.4**, 시행 **2025-03-20** / 확인 2026-07-13 | NAVER API 서비스 이용약관, 페이지 표기 **2018-07-18 개정**, 부칙 시행 **2020-03-05** / 확인 2026-07-13 | Kakao Developers 운영정책, 제19조 시행 **2026-04-20** / 확인 2026-07-13 | 이용약관 전문 ❓미확보(지오코더 가이드만 확인) / 확인 2026-07-13 |

[^kakao]: Kakao 운영정책은 명시 허용 조항 없이 금지 행동 목록(제5조)만 두므로, "표시
    허용"과 "UX 목적 cache 가능"은 **금지 조항 부재/단서에서의 반대해석**이다 — 확정
    판단이 아니며 사전 승낙 범위 확인이 필요하다(§7-10).

## 2. 근거 조항 상세 (확인일 2026-07-13)

### 2.1 YouTube Data API — [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies)

- **III.E.1 (Audiovisual Content)**: 사전 서면 승인 없이 YouTube audiovisual content를
  "download, import, backup, cache, or store" 금지.
- **III.E.4 (Refreshing, Storing, and Displaying API Data)**: API Data는 **최대
  30일**까지만 저장 가능("for no longer than 30 calendar days") — 이후 삭제 또는
  refresh. **주의: III.E.4.b의 무기한 저장 예외는 Authorized Data(사용자 OAuth 동의
  기반)에 한정**된다. 이 프로젝트의 수집은 **API key 기반 공개 metadata(Non-Authorized
  Data)**이므로 통계(조회수 등) 예외는 **적용 불가**하고, 30일 상한과 "temporarily
  store **limited amounts**" 제한이 그대로 적용된다. 이 30일 규칙은 **YouTube API
  metadata 범위로 정확히 한정**하고, 파생 POI 전체 삭제로 과도하게 확대하지
  않는다(로드맵 §10 B4).
- **III.E.6 (Scraping)** 및 비공식 API 사용 금지(III.D 계열): scraping·비공식 기술을
  통한 콘텐츠 접근 제한. `yt-dlp`·`youtube-transcript-api`는 비공식 수단에 해당한다
  (현재 아키텍처는 자막/프레임 구간에만 격리 — ADR-9·ADR-11).
- **III.F.2 (Branding)**: 콘텐츠 출처가 YouTube임을 명시(YouTube Brand Features 표시).
- **III.E.3 (Authorized Data Usage)**: Authorized Data는 승인한 사용자와 그 사용자가
  명시 승인한 대리인 외에 표시·접근 허용 금지.
- 문서 하단: "Last updated 2026-06-24 UTC".

### 2.2 Google Places — [Places API 정책](https://developers.google.com/maps/documentation/places/web-service/policies) · [Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms)

- **Service Specific Terms §14 (Places API — Legacy and New)** (원문 확인, 2026-07-13):
  - §14.1: "Customer may use Google Maps Content from the Places API in Customer
    Applications **without a corresponding Google Map**."
  - §14.2: "Customer must **not** use Google Maps Content from the Places API **in
    conjunction with a non-Google map**." — **VWorld 지도 위 Google 결과 표시는 이
    조항과 정면 충돌**한다.
  - §14.3: "Customer may temporarily cache latitude and longitude values from the
    Places API for up to **30 consecutive calendar days**, after which Customer must
    delete the cached latitude and longitude values."
  - (참고) §6 Geocoding API도 동일 구조: §6.2 비-Google 지도 금지, §6.3.1 lat/lng 30일,
    §6.3.2 특정 조건(요청을 발생시킨 End User 전용 기능, 사용자별 논리 격리)에서
    lat/lng·formatted_address·structured address 무기한 캐시 예외.
  - Service Specific Terms "Last modified June 10, 2026".
- **정책 페이지** (Last updated 2026-07-10 UTC):
  - "Exceptions from caching restrictions": **place ID는 캐싱 제한 예외 — 무기한 저장
    가능**("You can therefore store place ID values indefinitely").
  - attribution: 지도 없이 Places 데이터를 표시할 때 **Google 로고 포함 의무**
    ("you must include the Google logo"), 공간 제약 시 "Google Maps" 텍스트 허용.
- export: [Google Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms)
  **§3.2.3(a) "No Scraping"·(b) "No Caching"**이 Google Maps Content의 대량 취득과
  캐싱/저장을 일반 제한한다(허용 캐싱은 Service Specific Terms의 명시 예외뿐).
  **§3.2.3(c)(iv)**는 Google Maps Content 기반 파생 콘텐츠 생성(point-in-polygon 판정
  등)을 금지한다 — provider 유래 필드의 저장·export 검토(C-5/C-6)에서 함께 참고.
  Places content의 제3자 재배포는 허용으로 볼 근거 없음.

### 2.3 Naver — **두 제품을 구분한다**

이 저장소는 Naver를 두 갈래로 쓴다. **약관 주체·문서가 서로 다르다**:

1. **NCP Maps Geocoding** (`ktc/etl/geocoding.py`의 지오코딩 보조 검증, 실제 호출
   endpoint는 **구 게이트웨이 `naveropenapi.apigw.ntruss.com`**(`geocoding.py:221`) —
   네이버클라우드 계약. 신 게이트웨이(`maps.apigw.ntruss.com`)와 적용 약관 동일성은
   확인 필요 — 구 게이트웨이에는 AI·NAVER API 서비스 이용약관이 적용될 수 있다(§7-4)):
   [네이버 클라우드 플랫폼 Maps 서비스 이용약관](https://www.ncloud.com/policy/terms/maps)
   v0.4 (시행 2025-03-20, PDF 원문 확인 2026-07-13):
   - **제7조 ⑨**: "'고객'은 '회사'의 사전 동의 없이 '본 서비스'의 결과 데이터를 본
     약관에서 허용한 범위를 넘어서서 무단으로 복제, **저장**, 가공, 배포하거나
     제3자에게 제공해서는 안됩니다."
   - **제7조 ⑪**: "'본 서비스'의 결과 데이터를 … **별도로 저장해서는 안되며**, 따라서
     그와 같은 결과 데이터를 별도로 저장하는 방식으로 **데이터베이스화하여 이용해서도
     안됩니다**. … 모든 Maps API의 결과 데이터는 값을 리턴 받는 **즉시 1회** 자신의
     서비스에서 사용하는 것만 허용되며, 그렇지 않고 그 결과 값들을 별도로 저장, DB화,
     재사용하는 것은 금지됩니다."
   - **제7조 ⑩**: 회사 정책에 따라 결과 데이터/애플리케이션에 회사 로고·지정 표시
     게재를 요청할 수 있고 고객은 준수 의무.
   - **제7조 ⑫**: API·SDK 재판매 금지. — NCP Maps cache는 실제 계정 약관 확인 전
     **기본 off**로 둔다(로드맵 §10 B4, T-170 연계).
2. **NAVER Developers Local Search** (검수 화면 `place_search.py`의
   `openapi.naver.com/v1/search/local.json` — 개발자센터 계약): [NAVER API 서비스
   이용약관](https://developers.naver.com/products/terms/) (페이지 표기 2018-07-18 개정,
   부칙 시행 2020-03-05, 원문 확인 2026-07-13 — WebFetch 차단으로 curl로 원문 확보):
   - **7.3.③**: API로 취득한 정보를 "본 약관에서 허용한 범위를 넘어서서 무단으로 복제,
     **저장(캐시 행위 포함)**, 가공, 배포 등 이용하거나 제3자에게 제공하는 행위" 금지.
     명시 예: "**네이버 지역정보를 수집하여 별도 데이터베이스로 관리하며 이용하는
     행위**" 금지.
   - **7.3.⑥**: 어플리케이션 등을 통해 API 서비스를 다시 제3자에게 제공하는 행위 금지.
   - **7.3.⑨**: 네이버 BI 가이드(https://developers.naver.com/products/bi_guide) 준수.
   - **특약 2.1 (네이버 검색 API 서비스)**: "검색결과를 독립적으로 노출하여야 하며,
     검색결과의 앞, 뒤, 중간 등에 다른 내용을 삽입하거나 왜곡할 수 없고 … URL 등 API
     서비스로 제공되는 모든 내용을 회원이 임의로 수정 및 변조해서는 안 됩니다."
   - **8.1**: 결과 데이터의 저작권 등 제반 권리는 회사 또는 원저작자 등 제3자 귀속.

### 2.4 Kakao Local — [Kakao Developers 운영정책](https://developers.kakao.com/terms/ko/site-policies)

원문 확인 2026-07-13 (제19조 시행일: 2026-04-20 적용):

- **제5조(금지된 행동)**: "앱에서 **사용자 환경을 개선하기 위한 목적 외** 다른 목적으로
  카카오에서 받은 데이터를 캐시하거나 캐시 후 **최신 데이터로 유지하지 않는 행위**"
  금지 — 즉 UX 개선 목적 cache는 전면 금지가 아니며 **최신성 유지 의무**가 붙는다.
- **제5조(금지된 행동)**: "서비스 및 개발자센터를 이용하여 얻은 정보(예: 데이터, 비밀
  키, 엑세스 토큰 등 포함)를 카카오의 **사전 승낙 없이**, 복사, 복제, 변경, 번역, 출판,
  방송, 검색 엔진 또는 디렉터리에 입력 기타의 방법으로 사용하거나 이를 **타인에게
  제공하는 행위**" 금지(기밀유지계약 체결 대리인 예외).
- attribution 명시 조항: 운영정책 본문에서 확인하지 못함(❓) — 카카오맵 API(지도 SDK)
  약관은 별도이며 이 저장소는 지도 SDK를 쓰지 않는다.
- 구체 TTL 없음 — "모든 provider 60일" 같은 공통값을 쓰지 말고 계정·API별 허용 필드와
  TTL을 확인한다(로드맵 §10 B4, T-170).

### 2.5 VWorld — [지오코더 API 가이드](https://www.vworld.kr/dev/v4dv_geocoderguide2_s001.do)

- 공식 가이드 원문(확인 2026-07-13): "**API 요청은 실시간으로 사용하셔야 하며 별도의
  저장장치나 데이터베이스에 저장할 수 없습니다.**" 일 최대 40,000건 제한.
- 이용약관 전문(제10조 서비스 이용·제12조 저작권 등): 사이트가 JS 링크로만 노출해
  이번 확인에서 **원문 미확보 — ❓미확인·확인 필요**. 키 발급 시 동의한 조건과 데이터
  라이선스를 운영 기록으로 남겨야 한다(로드맵 §10 B4).
- 국토교통부/공간정보산업진흥원 운영 공공 서비스로, 발급 약정·공공데이터 라이선스에
  따라 위 문면보다 완화된 조건이 적용될 수 있으나 **확인 전 단정하지 않는다**.

## 3. 현재 코드 흐름과의 충돌 지점

| # | 현재 흐름 | 관련 코드 | 긴장 관계인 조항 |
|---|---|---|---|
| C-1 | **원본 미디어 무기한 보존 계약(ADR-15)** — `MEDIA_RETENTION_POLICY=infinite`, RustFS `kor-travel-concierge` 버킷에 원본 동영상/오디오 저장 | `backend/ktc/etl/frame_extraction.py`의 `store_raw_media`(현재 프로덕션 호출부는 없고 테스트만 존재 — 계약과 향후 PR-18/19가 확대 예정), `.env*`의 `MEDIA_RETENTION_POLICY` | YouTube Developer Policies **III.E.1** (사전 서면 승인 없는 다운로드·캐시·저장 금지) |
| C-2 | **yt-dlp 다운로드 경로** — 자막 파일 다운로드(`fetch_via_ytdlp`), whisper 폴백의 오디오(bestaudio→mp3) 다운로드(`transcribe_via_whisper`), 프레임 추출용 스트림 URL 확보(`resolve_stream_url_ytdlp`) | `backend/ktc/etl/transcript.py`, `backend/ktc/etl/frame_extraction.py` | III.E.1(오디오는 audiovisual content — 임시 tmpdir라도 다운로드 자체가 쟁점), III.E.6/III.D(비공식 수단 접근). **현재 dev·prod env 모두 `TRANSCRIPT_WHISPER_ENABLED=true`로 켜져 있어 오디오 다운로드가 실제로 발생 가능**(§6.2 인벤토리) |
| C-3 | **Google 결과의 VWorld 지도 표시** — 검수 화면 `/place-search`의 Google hit이 VWorld(maplibre) 지도에 마커로 표시되고 선택·저장 가능 | `backend/ktc/etl/place_search.py` `search_google_places`, `backend/ktc/api/routes.py` `/place-search`, 검수 프런트 지도 | Service Specific Terms **§14.2** (비-Google 지도와 함께 사용 금지). prod 403은 안전장치가 아니다 — 키 제한 문제일 뿐(T-151/T-154). **사용자 결정(2026-07-13): 현행 유지 — 인지된 정책 리스크로 운영**(§7-2) |
| C-4 | **Google 결과의 저장** — 검수에서 Google hit 선택 시 이름·주소·좌표가 `travel_places`/후보 evidence로 영구 저장될 수 있음 | 검수 resolve 경로(`place_service`), `provider_evidence_json`(T-065) | §14.3(lat/lng 30일 한도), 정책 페이지(저장 제한 — place ID만 무기한). **T-174는 Google 저장 차단을 기본으로 설계**(PR-31) |
| C-5 | **지오코딩 provider 결과의 영구 저장** — VWorld/Kakao/Naver 후보와 선택 결과를 `provider_evidence_json`(JSONB)·`travel_places` 좌표/주소로 보존 | `backend/ktc/etl/geocode_service.py`, `geocoding.py`, migration 20260610_0004 | NCP Maps **제7조⑨·⑪**(저장·DB화 금지), NAVER Developers **7.3.③**(지역정보 별도 DB 관리 금지), VWorld 가이드(실시간 사용·DB 저장 불가), Kakao 제5조(최신성 유지 의무). Google 유래 필드가 섞이는 경우 GMP ToS **§3.2.3(b)·(c)(iv)** 참고 |
| C-6 | **features API 외부 공급** — `/api/v1/features/snapshot`·`/changes`가 provider 유래 필드(좌표·주소·카테고리 등)를 downstream(`kor-travel-map`→PinVi)에 export | `backend/ktc/services/feature_export_service.py`, `docs/feature-export-api.md` | 각 provider의 제3자 제공 금지 조항(NCP 제7조⑨, NAVER 7.3.③·⑥, Kakao 제5조, Google GMP ToS §3.2.3(a)·(b) + 파생 생성 제한 §3.2.3(c)(iv)). **파생·독자 판단 데이터**(사용자 검수 확정, AI 카테고리 제안 등)와 **provider 원본 필드**의 경계 정의가 필요 |
| C-7 | **YouTube metadata 30일 규칙** — `youtube_videos`의 제목·설명·통계 등 metadata를 무기한 보존, 30일 refresh/delete 없음 | `backend/ktc/models/youtube_video.py`, 수집 파이프라인 | III.E.4 (30일 저장 후 삭제/refresh — 무기한 예외는 Authorized Data 한정이라 API key 수집인 본 프로젝트에는 **적용 불가**, §2.1). refresh/delete는 **metadata 범위로 한정**하고 파생 POI로 확대하지 않는다 |

## 4. Production kill switch (T-158에서 배선)

기본값은 **true = 현행 동작 유지**다 — 이 기본값은 사용자 결정(2026-07-13)으로
승인됐다(§7-11). prod 권고는 플래그별로 다르다(아래 표).

| env 플래그 | 기본 | prod 권고 | off일 때 동작 | 배선 지점 |
|---|---|---|---|---|
| `RAW_MEDIA_STORE_ENABLED` | `true` | `false` (ADR-15 재검토 결정 ①까지) | 원본 동영상/오디오 RustFS 저장을 스킵하고 로그 1줄(`store_raw_media` → `None`). 기존 객체는 삭제하지 않음 | `backend/ktc/core/config.py`, `backend/ktc/etl/frame_extraction.py::store_raw_media` |
| `GOOGLE_PLACE_SEARCH_ENABLED` | `true` | `true` (사용자 결정 2026-07-13 — 현행 유지, §7-2) | `/place-search`의 google 결과가 빈 목록 + `errors.google="disabled: …"` (HTTP 호출 자체를 생략) | `backend/ktc/core/config.py`, `backend/ktc/etl/place_search.py::search_google_places` |

**범위 주의**: `RAW_MEDIA_STORE_ENABLED`는 **저장** 게이트다 — **다운로드 자체는 이
플래그가 막지 않는다**. whisper 오디오 다운로드는 `TRANSCRIPT_WHISPER_ENABLED`가
게이트(사용자 의도로 활성 유지 — §7-8, 품질 개선은 T-193), 프레임 스트림
취득(yt-dlp)은 현재 게이트가 없다(향후 필요 시 별도 플래그).

**소관 구분**: provider **cache** kill switch는 캐시가 실제로 생기는 T-170 소관이고
(현재 지오코딩 cache 자체가 없어 끌 대상이 없다), Google 결과의 **저장** 전용 차단은
T-174 소관이다 — 이 PR의 범위는 표시(검색) 게이트에 의한 간접 차단까지다.

## 5. ADR-15 재검토 — ADR 초안 (사용자 결정 대기)

> `docs/decisions.md`에는 반영하지 않는다. 사용자 승인 후 ADR 번호를 받아 이동한다.
> **어떤 옵션이든 기존 RustFS 객체를 소급 삭제하지 않는다**(삭제는 별도 사용자 결정).

**초안 제목**: 원본 미디어 보존 계약(ADR-15) 재검토 — YouTube audiovisual content
저장의 compliance 게이트

**맥락**: ADR-15는 원본 동영상·자막·전사·프레임의 RustFS 무기한 보존을 계약으로
정했다. YouTube API Developer Policies III.E.1은 사전 서면 승인 없는 audiovisual
content의 다운로드·캐시·저장을 제한한다(§2.1). 자막 텍스트·전사 결과·파생 POI와
"audiovisual content"(영상·오디오 원본, 대표 프레임의 지위는 검토 필요)의 경계도
명확히 해야 한다.

**옵션**:

| 옵션 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A. compliance 확인 후 현행 유지 | YouTube 서면 승인(또는 해당 없음 확인)을 받고 ADR-15 유지 | 기능 손실 없음, 계약 유지 | 승인 획득 가능성 낮음·기간 불확실, 확인 전 리스크 지속 |
| B. 서면 승인 전 저장 중단 (**prod 권고**) | `RAW_MEDIA_STORE_ENABLED=false`로 원본 동영상/오디오 신규 저장 중단, 자막 텍스트·전사 결과·metadata(30일 규칙 적용)는 유지 | 즉시 리스크 축소, 코드 완성(T-158), 기존 객체 보존 | 원본 아카이브 목적(ADR-15) 일부 상실, 재처리 시 재다운로드 불가 |
| C. 사용자 제공 원본 경로 한정 | 권리가 확인된 사용자 업로드 원본만 저장(자동 yt-dlp 취득 금지) | 정책 충돌 없는 아카이브 유지, 명확한 권리 기반 | 업로드 UI/검증 등 신규 개발 필요, 자동 수집 영상은 커버 불가 |
| D. 보존 정책 변경 | 무기한 → 기한부(예: 처리 완료 후 N일) 또는 처리 즉시 삭제로 `MEDIA_RETENTION_POLICY` 변경 | 저장 최소화로 리스크·비용 축소 | "임시라도 다운로드·캐시 자체"가 III.E.1 쟁점이라 근본 해소 아님, 삭제 자동화는 금지 사항(RustFS 객체 자동 삭제 금지)과 조정 필요 |

**초안 권고**: 단기 B → 사용자가 아카이브 필요를 확정하면 C를 병행 개발. A는 병행
시도 가능. D는 단독으로는 불충분. (whisper는 별도 사용자 결정으로 활성 유지 — §7-8,
품질 개선은 T-193.)

## 6. 부록 — 인벤토리 (확인일 2026-07-13)

### 6.1 dev RustFS asset 인벤토리

시도 명령(WSL, boto3 — `.env`의 RustFS 자격 증명 사용, 값은 비노출):

```
boto3.client("s3", endpoint_url="http://127.0.0.1:12101", …).list_buckets()
→ 타 프로젝트 버킷 1개만 반환 (이 검토 범위 밖)

list_objects_v2(Bucket="kor-travel-concierge")
→ botocore.errorfactory.NoSuchBucket: An error occurred (NoSuchBucket) when calling
  the ListObjectsV2 operation: The specified bucket does not exist
```

**결과**: dev RustFS(`http://127.0.0.1:12101`)에는 `kor-travel-concierge` 버킷이
**존재하지 않는다**(2026-07-13 기준) — 즉 dev에는 현재 concierge 원본 미디어 asset이
0건이다(버킷은 첫 저장 시 lazy 생성 경로일 수 있음). 존재하는 버킷은 타 프로젝트 것
1개뿐으로 이 검토 범위 밖.

### 6.2 로컬 env 파일 (키 이름과 비밀 아닌 플래그만 — **비밀 값 비기록**)

- 워크트리에는 `.env`/`.env.production` 없음. 원본 리포(`F:\dev\kor-travel-concierge`)
  양쪽 모두 존재.
- **`.env` (dev)**: 설정된 키 — VWorld/Gemini/DeepSeek/YouTube/Kakao/Naver(geocoding·
  search)/Google Places/RustFS access·secret/admin 자격 등 표준 키 전부 값 있음.
  비밀 아닌 운영 플래그:
  - `APP_ENV`: **미설정** (코드 기본 `local`)
  - `TRANSCRIPT_WHISPER_ENABLED=true`, `WHISPER_MODEL_SIZE=base`
  - `GEMINI_RATE_RPM`/`RPD`/`TPM`: **미설정** (코드 기본 10 / 1,500 / 250,000)
  - `MEDIA_RETENTION_POLICY=infinite`, `RUSTFS_ENABLED=true`,
    `YOUTUBE_USE_OFFICIAL_API=true`
- **`.env.production` (로컬 사본)**: 공개 도메인 5종·`API_KEYS`·`BACKEND_API_KEY`·
  MCP basic_auth 등 값 있음(이름만 기록). 비밀 아닌 운영 플래그:
  - `APP_ENV=production`, `API_AUTH_ENABLED=true`
  - `TRANSCRIPT_WHISPER_ENABLED=true`, `WHISPER_MODEL_SIZE=base` — **prod에서도
    whisper(오디오 다운로드 경로)가 켜져 있음** → C-2 참고. **사용자 결정(2026-07-13):
    의도적 활성 유지**(자막 품질 개선은 T-193으로 분리 — §7-8)
  - `GEMINI_RATE_RPM`/`RPD`/`TPM`: **미설정** (코드 기본값 적용)
  - `MEDIA_RETENTION_POLICY=infinite`, `RUSTFS_ENABLED=true`,
    `YOUTUBE_USE_OFFICIAL_API=true`
  - 신규 kill switch 2종은 아직 양쪽 env에 없음(코드 기본 true) — prod 반영은 사용자
    결정 후.

### 6.3 prod 호스트 인벤토리 — **사용자 확인 필요** (이번 작업에서 접근하지 않음)

| 항목 | 상태 |
|---|---|
| 원격 prod 호스트(주소는 운영 기록 참조)의 RustFS `kor-travel-concierge` 버킷 asset 목록·용량 | ❓ 사용자 확인 필요 |
| prod에서 실제 로드되는 `.env.production` 값(로컬 사본과 drift 여부) | ❓ 사용자 확인 필요 |
| prod `API_KEYS` 각 키의 사용 주체 매핑(BFF `BACKEND_API_KEY` / `kor-travel-map` consumer `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY` / 기타) | ❓ 사용자 확인 필요 (B5/T-176 인벤토리와 연계) |
| prod whisper 실제 가동 여부(로그 기준 오디오 다운로드 발생 이력) | ❓ 사용자 확인 필요 |

## 7. 결정 필요 항목 (대기 항목과 확정 항목)

확정된 항목은 "**사용자 결정(2026-07-13)**"으로 표기한다. 나머지는 대기.

1. **[대기] ADR-15 재검토 옵션 선택** (§5 A/B/C/D) — 및 prod
   `RAW_MEDIA_STORE_ENABLED` false 적용 여부.
2. **[확정] Google Places 사용 형태 — 사용자 결정(2026-07-13): 현행 유지.**
   VWorld 지도 표시는 의도적 운영이며 **인지된 정책 리스크**(ST §14.2, C-3)로
   기록한다. release gate 관점에서 이 항목은 해소 처리(§0)하되 리스크 서술은
   보존한다. Google 결과의 **저장**은 별개 — T-174에서 차단이 기본.
3. **[대기] Naver Developers Local Search 결과의 저장 정책**: 7.3.③(별도 DB 관리
   금지)에 따라 검수 evidence 보존 범위(원본 필드 제외/최소화) 결정.
4. **[확정] NCP Maps cache — 사용자 결정(2026-07-13): T-170에서 정책 matrix 기반
   처리. NCP Maps 결과는 캐시·저장 대상에서 제외 확정.** T-170 진행 시 구 게이트웨이
   (`naveropenapi.apigw.ntruss.com`)와 신 게이트웨이(`maps.apigw.ntruss.com`)의
   **적용 약관 동일성 확인**(AI·NAVER API 이용약관 vs Maps 이용약관)을 포함한다.
5. **[대기] VWorld 이용약관 전문 확인**과 발급 조건·데이터 라이선스의 운영 기록화 —
   가이드 문면("실시간 사용, DB 저장 불가")과 현재 저장 흐름(C-5)의 해소 방안.
6. **[대기] features API export 필드 경계**: provider 원본 필드 vs 파생·검수 확정
   데이터의 구분 정의(C-6) — feature-export-api 계약에 반영 여부.
7. **[대기] YouTube metadata 30일 refresh/delete** 구현 여부와 범위 — C-7. 무기한
   예외는 Authorized Data 한정이라 API key 수집인 본 프로젝트에는 **적용 불가**(§2.1),
   파생 POI로는 확대하지 않는다.
8. **[확정] prod whisper — 사용자 결정(2026-07-13): 현행 유지(의도적 활성).**
   자막 품질 개선은 신규 태스크 **T-193**(whisper 모델 상향 평가·전사 품질 스코어링·
   재전사 정책 — T-164 데이터로 필요성 판단)으로 분리한다.
9. **[대기] 기존 RustFS 객체 처리**: dev는 0건(§6.1), prod는 인벤토리 확인 후
   보존/삭제 결정(자동 삭제 금지 — 사용자 결정·ADR 필수).
10. **[대기] Kakao 결과 저장·export 허용 필드 확인**: 운영정책 제5조의 "사전 승낙"
    범위 확인 — 현재 저장(카테고리 우선 사용 포함)·export 필드 중 승낙이 필요한
    범위를 확정한다(matrix 각주 [^kakao] 참고).
11. **[확정] kill switch 기본값 — 사용자 결정(2026-07-13): 현행 유지(true).**
    로드맵 PR-29의 "기본 안전측" 문면과의 이탈은 사용자 승인 사항으로 기록한다.
