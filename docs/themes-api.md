# Themes API (테마 중심 POI 공급)

본 문서는 `kor-travel-concierge`가 "특정 테마를 중심으로 POI를 가져가려는" 외부 소비자에게
제공하는 REST 계약의 정본이다. 구현은 아래 3개 엔드포인트이며 ADR-35(테마 중심 POI 공급),
ADR-24/ADR-36(`/api/v1` 버저닝·`X-API-Key` read scope), ADR-26(범용 feature 공급)에 정렬된다.

- `GET /api/v1/themes` — 공급 가능한 테마 목록(유튜버/재생목록/보정 검색어)
- `GET /api/v1/themes/places` — 한 테마의 확정 POI 목록
- `GET /api/v1/themes/video/{video_id}/places` — 한 동영상 테마의 확정 POI 목록(게이트)

> **전환 상태(T-190)**: `/themes/places`·`/themes/video/{id}/places`가 T-152 출시 시점의
> `{theme, places: [...]}` 전량 반환에서 PR-32 공통 envelope(`items`·`next_cursor`·`has_more`·
> `total`·`newest_id`·`newer_than`)로 전환됐다. 동시에 각 POI item의 `source_videos`는 기본
> 제외로 바뀌었고 `include=sources`로만 포함한다. **이는 파괴적 변경이다.** 아래
> "마이그레이션 노트"를 참조한다.

## 기본 원칙

- 인증은 feature API와 동일하다. 외부 소비자에는 DB에서 발급한 `read` scope 키만 전달하고
  `X-API-Key` header로 보낸다(`?key=`는 DB read 키에 한해 허용하지만 header를 권장한다).
  `admin`·정적 키는 외부 소비자와 공유하지 않는다. 로컬 `APP_ENV=local/test/e2e`는 ADR-24에
  따라 무인증 우회가 가능하다.
- "테마"는 두 종류다.
  1. **유튜버(channel) / 재생목록(playlist) / 보정 검색어(keyword)** — 그 출처에서 수집·확정된
     POI 전체를 테마로 묶는다.
  2. **특정 동영상(video)** — 그 동영상이 언급해 확정된 POI를 테마로 묶는다. 단,
     매치되거나 검수 완료된 POI가 **5개(`VIDEO_THEME_MIN_POIS`) 이상**일 때에만 목록을 공개한다.
- 확정 POI와 출처 근거 계산은 결과 보기(`/api/v1/destinations`)와 같은 규칙을 재사용한다
  (`place_service.list_place_summaries_page`, `video_place_mappings` ↔ `youtube_videos` 조인,
  `mention_count` 정렬).
- `kor-travel-concierge`는 `feature_id`를 만들지 않는다. 카테고리 8자리 제안
  (`category_code_suggestion`)만 노출하고 `feature_id`/`feature_snapshot` 생성은 consumer 책임이다.

## 공통 envelope

`/themes/places`·`/themes/video/{id}/places` 응답 top-level은 공통 목록 envelope에 테마
metadata를 더한 형태다.

| 필드 | 의미 |
| --- | --- |
| `items` | 이 페이지의 POI item 배열(POI item 스키마는 아래) |
| `next_cursor` | 다음 페이지 opaque cursor. 마지막 페이지면 `null` |
| `has_more` | 다음 페이지 존재 여부 |
| `total` | 현재 snapshot 기준 테마의 확정 POI 총수(페이지를 넘겨도 일정) |
| `newest_id` | snapshot watermark(최신 place id) |
| `newer_than` | `newer_than_id` 이후 새로 추가된 POI 수(미지정 시 `0`) |
| `theme` | 테마 metadata(`kind`/`value`/`poi_count` 등) |

`cursor`는 opaque string이며 소비자가 해석하지 않는다. cursor는 발급 시점의 정렬·filter에
묶이므로 다른 테마/파라미터에 재사용하면 `400`이 된다. `limit`은 기본 200, 상한 500으로 clamp된다.

## POI item 스키마

```json
{
  "place_id": 123,
  "name": "감천문화마을",
  "category": "관광지",
  "category_code_suggestion": "A02020700",
  "latitude": 35.09,
  "longitude": 129.01,
  "is_geocoded": true,
  "address": {
    "official_address": "...",
    "road_address": "...",
    "sigungu_code": "...",
    "sigungu_name": "...",
    "legal_dong_code": "...",
    "legal_dong_name": "..."
  },
  "mention_count": 3,
  "source_channel_count": 2
}
```

`source_videos`는 **기본 제외**한다(payload 경량화, T-152 철학). 출처 동영상 근거가 필요하면
`include=sources`로 요청한다. 이때 각 item에 아래 배열이 추가된다.

```json
"source_videos": [
  {
    "video_id": "abc",
    "video_title": "부산 여행 브이로그",
    "video_url": "https://youtu.be/abc",
    "channel_id": "UC...",
    "channel_title": "여행유튜버",
    "timestamp_start": "00:12:30",
    "timestamp_end": "00:13:10"
  }
]
```

## `GET /api/v1/themes`

공급 가능한 테마 목록과 각 테마의 확정 POI 수를 반환한다(T-177 envelope, 본 작업에서
변경하지 않음). 각 item은 `kind`/`value`/`title`/`poi_count`/`first_mapping_id`/`latest_mapping_id`.

파라미터: `limit`(1–500, 기본 100), `cursor`, `newer_than_id`.

## `GET /api/v1/themes/places`

한 테마(유튜버/재생목록/보정 검색어)의 확정 POI 목록.

파라미터:

| 파라미터 | 필수 | 설명 |
| --- | --- | --- |
| `kind` | 예 | `channel` / `playlist` / `keyword` |
| `value` | 예 | 채널 ID / 재생목록 ID / 보정 검색어 문자열 |
| `limit` | 아니오 | 페이지 크기(기본 200, 상한 500) |
| `cursor` | 아니오 | 다음 페이지 opaque cursor |
| `newer_than_id` | 아니오 | 이 place id 이후 신규 POI 수 계산용 |
| `include` | 아니오 | `sources`면 각 item에 `source_videos` 포함 |

```http
GET /api/v1/themes/places?kind=channel&value=UC...&limit=200
X-API-Key: ...
```

```json
{
  "items": [ /* POI item ... */ ],
  "next_cursor": null,
  "has_more": false,
  "total": 42,
  "newest_id": 987,
  "newer_than": 0,
  "theme": { "kind": "channel", "value": "UC...", "poi_count": 42 }
}
```

## `GET /api/v1/themes/video/{video_id}/places`

한 동영상 테마의 확정 POI 목록. **게이트**: 매치되거나 검수 완료된 POI가 5개 이상
(`sufficient=true`)일 때에만 `items`를 채운다. 미만이면 `sufficient=false`와 함께 빈 목록을
반환한다(정책상 미공개, 사유 노출). 게이트는 snapshot 전체 POI 수(`total`)로 판정하므로 페이지를
넘겨도 일관되며, 미공개일 때는 `next_cursor`/`has_more`를 노출하지 않는다.

파라미터: `limit`(기본 200, 상한 500), `cursor`, `newer_than_id`, `include`(=`sources`).

공개(≥5) 응답:

```json
{
  "items": [ /* POI item ... */ ],
  "next_cursor": null,
  "has_more": false,
  "total": 6,
  "newest_id": 987,
  "newer_than": 0,
  "theme": { "kind": "video", "value": "abc", "title": "부산 여행 6곳", "poi_count": 6 },
  "min_required": 5,
  "sufficient": true
}
```

미공개(<5) 응답:

```json
{
  "items": [],
  "next_cursor": null,
  "has_more": false,
  "total": 2,
  "newest_id": 987,
  "newer_than": 0,
  "theme": { "kind": "video", "value": "xyz", "title": "짧은 영상", "poi_count": 2 },
  "min_required": 5,
  "sufficient": false
}
```

## 오류

- `400` — 잘못된/불일치 cursor(다른 테마·파라미터에 재사용, 손상된 값 등).
- `422` — 파라미터 검증 실패(`kind` 미허용 값, `value` 누락, `limit` 범위 밖 등).
- `401`/`403` — 인증 실패 또는 부적절한 scope(비-local에서 read 키가 아님).

## 마이그레이션 노트 (T-190, 파괴적 변경)

`/themes/places`·`/themes/video/{id}/places`의 응답 형태가 다음과 같이 바뀌었다.

1. **`places` → `items`**: 최상위 `places` 배열이 공통 envelope의 `items`로 이동했다.
   페이지네이션 필드(`next_cursor`/`has_more`/`total`/`newest_id`/`newer_than`)가 추가됐다.
   `theme` 객체(`kind`/`value`/`poi_count`, 동영상은 `title`·`min_required`·`sufficient` 포함)는
   유지된다.
2. **`source_videos` 기본 제외**: POI item의 `source_videos` 배열이 기본 응답에서 빠졌다.
   좌표만 필요한 소비자의 payload가 줄어든다. 출처 근거가 필요하면 `include=sources`로 요청한다.

이 변경이 파괴적임에도 지금 적용하는 이유: 테마 API는 T-152에서 막 출시했고 **외부 소비자가
0**이다(운영 inventory 확인 — feature 공급 consumer인 `kor-travel-map`은 `/api/v1/features/*`만
사용하고 테마 엔드포인트는 호출하지 않는다. 브라우저 `/api-test` 진단 페이지가 유일한 호출부이며
본 작업에서 함께 갱신했다). 소비자가 붙기 전인 지금이 계약을 마감할 마지막 기회다. 추후 소비자가
생기면 이 문서가 정본 계약이 된다.
