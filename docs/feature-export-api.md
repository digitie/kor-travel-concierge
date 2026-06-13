# Feature export API

본 문서는 `kor-travel-concierge`가 YouTube 장소 후보를 외부 consumer에 제공하는 REST 계약의
정본이다. 구현은 `GET /api/v1/features/snapshot`과
`GET /api/v1/features/changes`이며, 최초 consumer는 `python-krtour-map`의
`kor-travel-concierge-youtube` provider다.

## 기본 원칙

- REST path에는 특정 downstream 이름을 넣지 않는다.
- 외부 호출자는 `X-API-Key`를 전송한다. 로컬 `APP_ENV=local/test/e2e`는 ADR-24에
  따라 무인증 우회가 가능하지만, consumer smoke는 실제 운영 경계와 같게
  `X-API-Key`를 보내는 방식으로 검증한다.
- `kor-travel-concierge`는 `feature_id`를 만들지 않는다. `feature_id`와 최종
  `feature_snapshot` 생성은 `python-krtour-map` 책임이다.
- TripMate는 `kor-travel-concierge` DB에 직접 붙지 않는다. TripMate의 여행 POI와 curated
  plan POI는 `python-krtour-map`이 만든 `feature_id`와 `feature_snapshot`을 자체
  POI row(`app.trip_day_pois`, `app.notice_pois`)에 저장한다.
- Curated plan은 feature row 자체의 모음이 아니라 TripMate가 소유한 feature 연계
  POI row들의 모음이다.
- 자동 TripMate POI 또는 curated plan 등록은 현재 범위가 아니다. 운영자는
  `python-krtour-map`에 적재된 YouTube 발 feature를 골라 TripMate POI 작성 흐름에
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

`operation=upsert` item은 다음 블록을 포함한다.

- `place`: 이름, 설명, 좌표, 주소, `category_label`, `category_code_suggestion`.
- `youtube`: video/channel/playlist id, title, URL, summary.
- `evidence`: timestamp, transcript excerpt, Gemini URL evidence, confidence,
  VWorld/Kakao/Naver provider evidence.
- `source_record`: provider `kor-travel-concierge-youtube`, dataset
  `youtube_place_candidates`, 원본 candidate id, payload hash.

TripMate feature 연계 POI row까지 이어지는 최소 입력은 다음과 같다.

| 용도 | export 필드 | 소비 흐름 |
| --- | --- | --- |
| 표시명 | `place.name` | `python-krtour-map` feature name → TripMate POI `feature_snapshot.name` |
| 좌표 | `place.longitude`, `place.latitude` | feature coord → TripMate POI `feature_snapshot.coord` |
| 카테고리 | `place.category_code_suggestion` | krtour category → marker icon/color와 TripMate POI 표시 카테고리 |
| 영상 근거 | `youtube.video_url`, `evidence.timestamp_*`, `evidence.confidence_score` | krtour feature detail → TripMate POI 출처 배지/운영 추적 |
| 원천 추적 | `source_record.raw_payload_hash`, `source_record.source_entity_id` | krtour `SourceRecord`/`SourceLink` lineage |

TripMate curated plan smoke는 이 API item을 곧바로 plan item으로 간주하지 않는다.
먼저 `python-krtour-map` feature 적재 결과에서 `feature_id`와 `feature_snapshot`을
얻고, TripMate가 `app.notice_pois` row를 만든 뒤 curated plan이 그 POI row를
포함하는지 확인한다.

## Operation 의미

- `upsert`: 검수 통과 후보 또는 payload 변경 후보.
- `reject`: 과거 export된 후보가 검수에서 제외됨.
- `tombstone`: 과거 export 후보가 더 이상 유효하지 않음.

`python-krtour-map`은 `reject`와 `tombstone`을 대응 feature의
`status='inactive'` 전환으로 처리한다. `kor-travel-concierge`는 RustFS 객체나 과거 원본을
삭제하지 않는다.
