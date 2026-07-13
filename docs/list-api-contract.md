# 목록 API 공통 계약

본 문서는 검수·작업·장소·테마 목록의 pagination 계약 정본이다. 대상은 다음 네 경로다.

- `GET /api/v1/destinations/unmatched`
- `GET /api/v1/runs`
- `GET /api/v1/destinations`
- `GET /api/v1/themes`

`GET /api/v1/features/snapshot`과 `GET /api/v1/features/changes`는 실제 외부 consumer가
사용하는 별도 sequence cursor 계약이므로 이 문서의 공통 cursor를 적용하지 않는다.

## 2026-07-13 응답 전환 안내

이번 변경은 `/api/v1`의 네 목록 응답을 명시적으로 바꾸는 breaking 변경이다. 저장소 내부
프런트는 호환 wrapper로 기존 화면을 유지하지만, 직접 REST consumer는 다음과 같이 옮겨야 한다.

- `/runs`, `/destinations`, `/destinations/unmatched`: 기존 최상위 배열 대신 새 응답의
  `items`를 읽는다.
- `/themes`: 기존 `{channels,playlists,keywords}` 대신 `items`를 읽고 각 항목의
  `kind=channel|playlist|keyword`로 필요한 그룹을 만든다. 항목에는
  `first_mapping_id`·`latest_mapping_id`가 추가된다.
- 전체가 필요하면 `has_more=true`인 동안 `next_cursor`를 다음 요청의 `cursor`로 그대로
  전달한다. cursor를 해석하거나 조합하지 않는다.
- `/runs`와 `/destinations`에서 `limit`을 0 이하 또는 endpoint 최대값보다 크게 보내면 과거의
  조용한 clamp 대신 422를 반환한다. `/destinations/unmatched`는 기존처럼 범위 밖 422이며,
  `/themes`는 새 pagination 도입과 함께 같은 검증을 적용한다.

```text
response = GET 목록?limit=...  # 첫 page는 cursor query를 생략
consume(response.items)
while response.has_more:
  response = GET 목록?limit=...&cursor=response.next_cursor
  consume(response.items)
```

범용 feature 두 경로는 이 전환 대상이 아니며 기존 3필드 응답을 유지한다.

## 응답 envelope

```json
{
  "items": [],
  "next_cursor": null,
  "has_more": false,
  "total": 0,
  "newest_id": null,
  "newer_than": 0
}
```

- `items`: 현재 page 항목이다.
- `next_cursor`: `has_more=true`일 때만 다음 요청에 전달할 opaque 문자열이다. 마지막
  page에서는 `null`이다.
- `has_more`: 같은 snapshot에 다음 page가 실제로 있는지 `limit + 1` 조회로 판정한다.
- `total`: cursor 경계 적용 전, 현재 요청의 filter와 첫 page watermark를 만족한 전체 수다.
  더 큰 ID의 insert에는 영향받지 않지만 상태 전이·삭제·filter 대상 값 수정은 반영될 수 있다.
- `newest_id`: 첫 page filter 집합의 최대 단조 ID이며 빈 집합은 `null`이다. 테마는 파생
  catalog라 `video_place_mappings.id` watermark를 쓴다.
- `newer_than`: `newer_than_id`보다 큰 ID를 같은 filter로 실제 count한 값이다. ID 차이를
  사용하지 않으므로 sequence gap·삭제가 있어도 정확하다. 인자를 생략하면 `0`이다. 테마는
  `first_mapping_id`가 기준보다 큰 새 테마만 세며, 기존 테마의 mapping 추가나 제목 수정은
  새 항목으로 세지 않는다.

`newer_than_id`는 동일한 endpoint·filter에서 받은 `newest_id`에만 사용한다. filter를 바꾸면
기준값도 버려야 한다.

## Cursor와 ID watermark

cursor는 URL-safe base64로 감싼 versioned JSON이며 다음 정보를 보존한다.

- cursor version
- endpoint·정렬·정규화한 filter의 SHA-256 fingerprint
- 첫 page의 snapshot watermark
- 마지막 반환 항목의 전체 정렬 key

서버는 구조·version·key 개수와 타입·fingerprint를 검증한다. 다른 endpoint·정렬·filter에
cursor를 재사용하거나 훼손된 값을 보내면 400이다. `limit`, `cursor`, `newer_than_id`는
fingerprint에서 제외하므로 page 중간에 `limit`을 바꿀 수 있다.
cursor는 최대 4,096자이며 ID 입력은 PostgreSQL `INTEGER` 범위인 0~2,147,483,647만 허용한다.

fingerprint는 cursor 오사용 방지 장치이지 인증 정보나 위변조 방지 서명이 아니다. cursor는
조회 권한을 부여하지 않으며 모든 요청은 기존 API 인증 경계를 그대로 통과해야 한다. 특히
T-185의 일괄 검수 preview·확인 같은 쓰기 계약의 승인 token으로 이 cursor를 재사용하지 않는다.
쓰기 승인은 별도 만료 시간과 HMAC 서명을 가진 token으로 설계한다.

첫 page에서 `newest_id`를 watermark로 고정하고 다음 page는 그 이하 ID만 조회한다. 따라서
page 사이에 더 큰 ID가 추가돼도 기존 순회에 끼어들지 않으며 `newer_than`으로 따로 감지한다.
이는 PostgreSQL transaction snapshot을 보관하는 계약이 아니다. 상태 전이·삭제·filter 값 또는
장소 이름·카테고리·언급 수 같은 정렬 key가 page 사이에 수정되면 `total`과 항목 위치가 바뀔 수
있다. 완전한 반복 읽기가 필요하면 materialized 목록 snapshot을 별도로 도입해야 한다. T-188 SQL
pushdown에서 PostgreSQL collation과 정렬 계약이 바뀌면 cursor scope version을 올려 구 cursor를
400으로 명시적으로 만료한다.

## Endpoint별 정렬

| 목록 | 정렬 key | 최대 `limit` | 단건 직접 조회 |
|---|---|---:|---|
| 검수 | `id DESC` | 2,000 | `/destinations/candidates/{candidate_id}/detail` |
| 작업 | `id DESC` | 100 | `/runs/{job_id}` |
| 장소 최신 | `place_id DESC` | 500 | `/destinations/{place_id}/detail` |
| 장소 언급 | `mention_count DESC, source_channel_count DESC, name ASC, place_id DESC` | 500 | 동일 |
| 장소 이름 | `name ASC, place_id DESC` | 500 | 동일 |
| 장소 카테고리 | `category ASC, name ASC, place_id DESC` | 500 | 동일 |
| 테마 | `kind, poi_count DESC, title, value` | 500 | `/themes/places?kind=&value=` |

장소 목록은 T-188 전까지 기존 Python 집계·filter semantics를 보존한 채 동일 정렬 key로
cursor를 적용한다. 따라서 이 단계는 접근 완결성과 응답 크기를 고치지만 page별 DB 집계 비용을
줄이지 않는다. 전체 순회가 필요하면 endpoint 최대 `limit`을 사용하고, 작은 `limit` 반복 호출로
부하를 키우지 않는다. T-188은 SQL pushdown과 상세 근거 지연 로딩을 맡고, T-190은 테마 집계·
장소 목록 비용과 공개 payload를 마감한다.

## Filter 정규화

- 작업 `job_types`는 쉼표 분리 뒤 공백 제거·중복 제거·정렬한다.
- 검수는 `channel_id`, `playlist_id`, `keyword`와 암묵 조건
  `needs_review AND deleted_at IS NULL`을 고정한다.
- 장소는 `sort`, 출처 4종, `category`, `q`, `district`를 포함하며 `q`만 실제 검색과 같이
  앞뒤 공백 제거·소문자화한다.
- 빈 선택형 filter는 `null`과 같은 의미로 정규화한다.
- 작업 `state`는 32자, `job_types`는 최대 10개·항목당 64자로 제한한다.
- YouTube channel·playlist·video ID는 128자, 검색어·`q`는 255자, category는 64자,
  district는 128자로 제한한다.

## 프런트 전환

T-178부터 결과 화면은 `listDestinationsPage`를 직접 사용해 100개 단위로 cursor를 append한다.
`has_more`만 종료 기준으로 삼고, dedupe 뒤 표시 수와 live `total`이 다르면 완료로 단정하지 않고
목록 변경 안내와 수동 새로고침을 제공한다. page가 둘 이상이면 T-188 SQL pushdown 전 전체 집계
polling을 중단하고 명시적 새로고침으로 전환한다. 기존 `listDestinations` 배열 wrapper는 제거했다.

나머지 `listRunsPage`, `listUnmatchedCandidatesPage`, `listThemesPage`는 호환 wrapper로 현재 화면을
보존한다. 후속 T-183·T-190·T-192에서 각 화면이 metadata와 cursor를 직접 사용한다.
