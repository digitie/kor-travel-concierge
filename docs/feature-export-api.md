# Feature export API

본 문서는 `kor-travel-concierge`가 YouTube 장소 후보를 외부 consumer에 제공하는 REST 계약의
정본이다. 구현은 `GET /api/v1/features/snapshot`과
`GET /api/v1/features/changes`이며, 최초 consumer는 `kor-travel-map`의
`kor-travel-concierge-youtube` provider다.

> **전환 상태**: T-175의 DB read key capability를 바탕으로 T-176에서 production consumer의
> read key 발급·인증 정보 교체·구 정적 admin 항목 제거를 완료했다. n150에서 snapshot/changes
> 각각 opaque cursor 2페이지 확인과 1,416개 전체 순회, 실제 Dagster 가져오기 결과, read 공급 GET 200·
> write/내부 GET 403, 구 admin key 401을 검증했다. key 값은 어떤 추적 문서에도 기록하지 않는다.

## 기본 원칙

- REST path에는 특정 downstream 이름을 넣지 않는다.
- 외부 소비자에는 DB에서 발급한 `read` scope 키만 전달하고 `X-API-Key` header로
  전송한다. `read` 키는 이 feature API를 포함한 명시적 공급 GET만 호출할 수 있으며,
  내부 조회와 모든 쓰기는 403이다. VWorld 호환 `?key=`도 DB read 키에 한해 허용하지만
  access log·browser history 노출을 줄이기 위해 header를 권장한다. admin·정적 키는 query로
  전달할 수 없다. 로컬 `APP_ENV=local/test/e2e`는 ADR-24에 따라 무인증 우회가 가능하지만,
  consumer smoke는 실제 운영 경계와 같게 read 키 header를 보내는 방식으로 검증한다.
- 잘못된 scope로 발급한 키는 수정하지 않고 폐기 후 재발급한다. BFF/operator용 정적 admin
  키를 외부 소비자와 공유하지 않는다.
- `kor-travel-concierge`는 `feature_id`를 만들지 않는다. `feature_id`와 최종
  `feature_snapshot` 생성은 `kor-travel-map` 책임이다.
- PinVi는 `kor-travel-concierge` DB에 직접 붙지 않는다. PinVi의 여행 POI와 curated
  plan POI는 `kor-travel-map`이 만든 `feature_id`와 `feature_snapshot`을 자체
  POI row(`app.trip_day_pois`, `app.notice_pois`)에 저장한다.
- Curated plan은 feature row 자체의 모음이 아니라 PinVi가 소유한 feature 연계
  POI row들의 모음이다.
- 자동 PinVi POI 또는 curated plan 등록은 현재 범위가 아니다. 운영자는
  `kor-travel-map`에 적재된 YouTube 발 feature를 골라 PinVi POI 작성 흐름에
  넣고, curated plan은 저장된 POI row들을 묶어서 만든다.

## `GET /api/v1/features/snapshot`

현재 활성 `upsert` 후보만 full snapshot으로 반환한다.

요청:

```http
GET /api/v1/features/snapshot?cursor=<opaque>&limit=200
X-API-Key: ...
```

응답 top-level은 envelope 없이 다음 형태다.

```json
{
  "items": [],
  "next_cursor": "MQ==",
  "has_more": false
}
```

`cursor`는 opaque string이며 consumer가 해석하지 않는다. `limit`은 1 이상 500 이하로
clamp된다.

응답 스키마는 OpenAPI에 `FeatureExportPageResponse`(`items`/`next_cursor`/`has_more`)로
노출한다. item 스키마는 명시 필드 외의 키를 보존하는 개방형(`additionalProperties`)이라,
새 필드는 스키마 변경 없이 추가될 수 있다(비파괴 계약).

**snapshot 페이징 중 item 재등장 규칙**: snapshot은 `sequence` 오름차순 keyset 페이징이다.
한 소비 세션이 여러 페이지를 넘기는 동안 이미 지나간 item의 payload가 갱신되면(예: 지오코딩
보강) 그 item은 더 큰 `sequence`로 재발행되어 **뒤 페이지에 다시 나타날 수 있다**(중복 가능).
반대로 아직 지나가지 않은 item이 갱신돼도 유실되지 않는다. 소비자는 `export_id` 기준 upsert
(멱등 병합)로 처리하므로 중복은 안전하고, 누락은 발생하지 않는다.

## `GET /api/v1/features/changes`

`upsert`, `reject`, `tombstone` 변경을 sequence cursor 순서로 반환한다.

```http
GET /api/v1/features/changes?cursor=<opaque>&limit=200
X-API-Key: ...
```

`has_more=true`인 응답은 반드시 비어 있지 않은 `next_cursor`를 포함해야 하며, 다음
요청의 cursor로 전달했을 때 단조 전진해야 한다. 변경이 없으면 `items=[]`,
`has_more=false`로 200을 반환한다.

## Item payload

item은 top-level `schema_version`(정수, 현재 `1`)과 다음 블록을 포함한다. `schema_version`은
payload 계약 버전이며, 계약 확장은 **additive**(새 필드·새 error `code`)라 소비자는 이 값을
무시해도 된다. 파괴적 스키마 변경이 필요할 때만 증가하며, 그 경우 전 item이 새 sequence로
재발행되어 자연스럽게 재수신된다.

`operation=upsert` item은 다음 블록을 포함한다.

- `place`: 이름, 설명, 좌표, `address`, `category_label`, `category_code_suggestion`.
- `youtube`: video/channel/playlist id, title, URL, summary.
- `evidence`: timestamp, transcript excerpt, Gemini URL evidence, confidence,
  VWorld/Kakao/Naver provider evidence.
- `source_record`: provider `kor-travel-concierge-youtube`, dataset
  `youtube_place_candidates`, 원본 candidate id, payload hash.

### `place.address` 행정코드

`place.address`는 확정 장소(`travel_places`)의 실데이터에서 채운다.

| 필드 | 출처 | 규칙 |
| --- | --- | --- |
| `official_address` / `road_address` | 지오코딩 결과 | 없으면 `null` |
| `sigungu_code` | `travel_places.sigungu_code`(5자리) | 없으면 `null` |
| `legal_dong_code` | `travel_places.legal_dong_code`(10자리) | 없으면 `null` |
| `sido_code` | **앞 2자리 유도**: `sigungu_code[:2]` 우선, 없으면 `legal_dong_code[:2]` | 둘 다 `null`이면 `null` |

`sido_code` 전용 컬럼은 두지 않는다. 행정표준 코드의 앞 2자리가 시도 코드라는 규칙을 이용해
유도한다(경량 옵션). `sigungu_code`가 있으면 그 앞 2자리를, 없고 `legal_dong_code`만 있으면
법정동 코드 앞 2자리를 쓴다. 시군구·법정동 코드가 모두 없으면 유도 결과도 `null`이다.

PinVi feature 연계 POI row까지 이어지는 최소 입력은 다음과 같다.

| 용도 | export 필드 | 소비 흐름 |
| --- | --- | --- |
| 표시명 | `place.name` | `kor-travel-map` feature name → PinVi POI `feature_snapshot.name` |
| 좌표 | `place.longitude`, `place.latitude` | feature coord → PinVi POI `feature_snapshot.coord` |
| 카테고리 | `place.category_code_suggestion` | krtour category → marker icon/color와 PinVi POI 표시 카테고리 |
| 영상 근거 | `youtube.video_url`, `evidence.timestamp_*`, `evidence.confidence_score` | krtour feature detail → PinVi POI 출처 배지/운영 추적 |
| 원천 추적 | `source_record.raw_payload_hash`, `source_record.source_entity_id` | krtour `SourceRecord`/`SourceLink` lineage |

PinVi curated plan smoke는 이 API item을 곧바로 plan item으로 간주하지 않는다.
먼저 `kor-travel-map` feature 적재 결과에서 `feature_id`와 `feature_snapshot`을
얻고, PinVi가 `app.notice_pois` row를 만든 뒤 curated plan이 그 POI row를
포함하는지 확인한다.

## Operation 의미

- `upsert`: 검수 통과 후보 또는 payload 변경 후보.
- `reject`: 과거 export된 후보가 검수에서 제외됨.
- `tombstone`: 과거 export 후보가 더 이상 유효하지 않음.

`kor-travel-map`은 `reject`와 `tombstone`을 대응 feature의
`status='inactive'` 전환으로 처리한다. `kor-travel-concierge`는 RustFS 객체나 과거 원본을
삭제하지 않는다.

## 오류 응답

잘못된 요청은 400과 함께 `detail` object를 반환한다. `detail`은 한국어 `message`를 유지하되
기계가 분기할 수 있는 `code`를 additive로 포함한다.

```json
{ "detail": { "code": "invalid_cursor", "message": "유효하지 않은 cursor: ..." } }
```

- `invalid_cursor`: `cursor`가 opaque 계약을 벗어남(디코드 실패).
- `invalid_params`: 그 밖의 파라미터 오류.

`limit`이 `[1, 500]` 밖이면 FastAPI 검증 단계에서 422로 거부한다(위 `code` 셋과 별개).

이전 계약에서 `detail`은 문자열이었다. 오류 body를 `{code, message}` object로 바꾼 것은
로드맵 요구이며(에러 계약 마감), `message`에 기존 한국어 문구를 보존해 사람이 읽는 값은
동일하다. 정상 소비자는 서버가 준 opaque `cursor`를 그대로 재사용하므로 `invalid_cursor`에
도달하지 않는다(오류 body 변경의 실질 영향 없음).

## 스키마 확장·재발행(재배포)

계약 변경은 **additive**만 허용한다. 새 필드·새 error `code`는 추가하되, opaque base64
`cursor`, `operation`(`upsert`/`reject`/`tombstone`), `sequence` 단조 증가 계약은 불변이다.

payload 필드를 바꾸는 배포(예: `place.address` 행정코드 주입, `schema_version` 도입)는
해당 export의 `payload_hash`를 바꾸므로, 그 item들이 새 `sequence`로 **재발행**된다.
재발행은 두 경로로 자연 처리된다.

1. payload를 바꾸는 mutation은 dirty outbox에 실려 공급 GET(`sync_dirty`)이 즉시 재발행한다(T-171).
2. 배선을 우회한 변경(배포 시 코드만 바뀌어 기존 row의 hash가 달라지는 경우)은 프로세스 시작
   1회 + 시간당 1회 도는 전량 reconcile 안전망(`sync_feature_exports`)이 최대 1시간 내
   재발행한다.

따라서 **행정코드 주입·`schema_version` 도입 배포 후에는 관련 전 item이 재발행된다**.
`kor-travel-map`은 별도 조치 없이 다음 pull에서 재수신하면 되고, 보유한 `cursor`는 그대로
유효하다(단조 전진). 즉시 전량 재동기화가 필요하면 운영자가 스케줄 밖에서
`sync_feature_exports`를 1회 수동 실행할 수 있다.

이 자동 재발행은 **전량 reconcile 안전망이 활성(기본 켜짐)**임을 전제로 한다. reconcile을 끈
운영 환경에서는 payload 필드를 바꾸는 mutation 경로(dirty outbox)를 타지 않은 배포성 변경이
재발행되지 않으므로, 배포 직후 `sync_feature_exports`를 1회 수동 실행해야 한다.

**롤아웃/롤백 절차(운영 문서, 코드로 canary를 만들지 않는다)**:

- 배포 시점: 전량 재발행 1사이클(`sync_feature_exports`)은 feature-export advisory lock을
  트랜잭션 동안 잡으므로, 그동안 공급 GET이 잠깐 대기할 수 있다. **저트래픽 시간대 배포를
  권고**한다(소비자 폴링 지연만 발생하고 유실은 없다).
- canary: 배포 후 `snapshot` 1페이지를 read 키로 조회해 `schema_version=1`과
  `place.address.sido_code` 유도가 정상인지 확인한다.
- cursor drain: 소비자는 보유 `cursor`로 `changes`를 계속 폴링한다. 재발행 upsert가 순서대로
  흘러오며 유실은 없다(중복은 `export_id` 멱등 병합으로 흡수).
- rollback: payload 필드를 이전으로 되돌리면 hash가 다시 바뀌어 같은 재발행 흐름으로 원복된다.
  ledger·cursor·sequence 계약은 불변이므로 소비자 재설정은 필요 없다.

## 관련: 장소 목록 export의 `geocoded_only`

feature 공급 API와 별개로, 운영자용 장소 목록 export
`GET /api/v1/destinations/export`(`xlsx`/`gpx`/`kml`)에 `geocoded_only` 쿼리 파라미터가 있다.
확정 좌표(`travel_places.is_geocoded`)가 없는 장소를 제외할지 결정한다.

- **미지정(기본)**: 포맷 기반 기본값 — `gpx`/`kml`은 `true`(지오 플롯 포맷은 좌표 없는 항목이
  무의미해 제외), `xlsx`는 `false`(데이터 포맷이라 조용한 행 탈락을 피해 전체 포함).
- **명시값**: `geocoded_only=true|false`는 포맷과 무관하게 그대로 존중한다(opt-in/opt-out).

이 규칙은 "미검증 좌표의 지오 포맷(GPX/KML) 유출 방지"가 목적이며, xlsx 같은 데이터 포맷에는
강제 필터를 걸지 않는다. 주의: `ids`로 특정 장소를 선택해도 `gpx`/`kml` 기본값(`true`)에서는
미지오코딩 선택 항목이 결과에서 빠질 수 있다. 반드시 포함하려면 `geocoded_only=false`.
이 파라미터는 `/features/*` 공급 계약에는 영향을 주지 않는다.
