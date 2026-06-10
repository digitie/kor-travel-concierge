# cross-repo 일관성 검토 — tripmate-agent 측 반영 항목 (2026-06-10)

> **출처**: python-krtour-map repo에서 수행한 3-시스템(krtour-map · TripMate ·
> tripmate-agent) 완성도·정합성 교차 검토의 tripmate-agent 측 산출물.
> 전체 검토는 python-krtour-map `docs/reports/service-completeness-review-2026-06-10.md`,
> 실행 계획은 같은 위치 `consistency-uplift-plan-2026-06-10.md` 참조.
> **기준 커밋**: tripmate-agent `origin/main` `a443ca0`(#55) · krtour-map `origin/main`
> `0e45bd7`(T-216 + TripMate-agent provider) · TripMate `origin/main` `4a10a5b`(#149).
>
> 본 문서는 정보 전달용이며, 기존 정본(decisions.md/tasks.md 등) 반영은 사용자 승인 후 진행.

---

## 1. 가장 중요한 사실: krtour-map 측 소비자 구현이 이미 완료됨

krtour-map `0e45bd7`에 **TripMate-agent YouTube provider가 전부 구현·머지**되어 있다
(ADR-049). T-066은 더 이상 "설계 합의 대기"가 아니라 **상대측이 기다리는 구현**이다.

krtour-map 측 실측 (이 계약을 어기면 즉시 적재 실패):

| 항목 | krtour-map 구현 값 | 근거 |
|---|---|---|
| 호출 경로 (**현재 main 구현**) | `GET {base}/api/v1/krtour/features/{snapshot\|changes}` — endpoint 선택은 consumer 설정 `tripmate_agent_feature_sync_endpoint` | `packages/krtour-map-dagster/.../provider_fetchers.py:87` (krtour `origin/main` 기준) |
| 호출 경로 (**목표 — 경로 중립화**) | `GET {base}/api/v1/features/{snapshot\|changes}` — downstream 이름 제거. krtour-map#334(ADR-050 #1 제안)의 T-217a로 fetcher 정렬 예정. **T-066은 목표 경로로 구현하되, 배포는 krtour T-217a와 동시**(한쪽만 나가면 404/적재 실패) | krtour-map#334 (열린 PR) |
| 인증 | `X-API-Key` 헤더 (tripmate-agent `API_KEYS` 중 하나) | 같은 파일 `:89` |
| 요청 파라미터 | `limit`(krtour 설정 `tripmate_agent_feature_page_size`), `cursor`(opaque) | `:96-100` |
| 응답 필수 형태 | JSON object — `items: list` 필수, `has_more: bool`, `next_cursor: str` | `:104-118` |
| cursor 규약 | `has_more=true`면 `next_cursor` 비어있으면 안 되고, **직전 cursor와 같으면 에러**(무한루프 가드) — cursor는 단조 전진해야 함 | `:112-124` |
| krtour 측 env | `KRTOUR_MAP_TRIPMATE_AGENT_BASE_URL`, `KRTOUR_MAP_TRIPMATE_AGENT_API_KEY`, timeout | `:72-84` |
| provider 식별 | provider `tripmate-agent-youtube`, dataset `youtube_place_candidates` | krtour `src/krtour/map/providers/tripmate_agent.py` |
| operation 처리 | **`upsert`만 적재. `reject`/`tombstone`은 현재 skip** (krtour 측 후속 과제로 식별됨 — 아래 §3 D-03) | 같은 파일 `:76,87` |

본 repo `docs/youtube-feature-pipeline-plan.md` §7의 스키마와 위 기대치는 **일치함을
확인**했다 (필드명·페이지네이션·operation 모두). 즉 T-066은 plan §7대로 구현하면 된다.

사용자 보정에 따라 REST path에는 특정 downstream 이름을 넣지 않는다.
만약 sibling repo 구현 또는 설정 기본값이 이전 downstream 전용 경로를 가리키고
있다면 T-067에서 `/api/v1/features/*`로 함께 정렬해야 한다.

> **2026-06-10 결정 반영 — merge dependency 주의**: 경로 중립화(ADR-050 #1)와
> fetcher 정렬 task(T-217a)는 **아직 열린 PR `digitie/python-krtour-map#334`의 내용**
> 이다 — 본 문서에서 인용하는 ADR-050~052·T-217a~g 전부 동일 (krtour 현재 main에
> 머지된 것은 ADR-049까지). #334 머지 전에는 "제안/대기 중"으로 읽을 것. 본 PR(#56)은
> **#334 머지 후에 머지**하는 것을 권장한다.
> **양쪽 동시 배포 필수** — T-066 배포 시점에 krtour-map T-217a가 함께 나가야
> 적재가 끊기지 않는다 (현재는 양쪽 다 미가동이라 안전).

## 2. tripmate-agent 액션 (TA-)

- **TA-01 🔴 — T-066 export API 구현 시 준수 체크리스트**
  - [ ] `GET /api/v1/features/snapshot` — full resync 가능해야 함 (plan §7.1)
  - [ ] `GET /api/v1/features/changes` — `(updated_at, export_id)` 또는 별도
        sequence 기반 **단조 전진 cursor** (위 무한루프 가드 주의: 같은 cursor 반복 반환 금지)
  - [ ] 응답 top-level: `{items, has_more, next_cursor}` — krtour `{data,meta}` envelope을
        따라하지 말 것 (krtour fetcher가 top-level `items`를 읽는다)
  - [ ] `limit` 쿼리 파라미터 수용 (기본/최대값은 본 repo가 정의하되 krtour 설정
        `tripmate_agent_feature_page_size`와 운영 합의)
  - [ ] `X-API-Key` 인증 — krtour 전용 키를 `API_KEYS`에 별도 발급 권장 (감사 추적 분리)
  - [ ] `operation` 필드: `upsert`/`reject`/`tombstone` (plan §7.2)
  - [ ] 빈 결과(`items: []`, `has_more: false`)도 200으로 — fetcher는 4xx/5xx에서
        `raise_for_status()`로 즉시 실패한다
  - [ ] 통합 테스트: krtour fetcher 시뮬레이션(2페이지 이상 + 증분 + 같은-cursor 가드)
- **TA-02 🟡 — 계약 정본 문서 독립** ✅ D-04 **(a) 확정 (2026-06-10, krtour ADR-050 #2)**
  - `youtube-feature-pipeline-plan.md` §7은 계획 문서라 완료 후 동결됨. 독립 계약 문서
    (예: `docs/feature-export-api.md`)로 분리해 **공급자인 본 repo가 정본을 보유**하고,
    krtour-map `docs/rest-api.md` 계열에서 링크하도록 한다 (krtour ADR-044 관행:
    데이터 정합성 1차 책임 = 공급 측). FastAPI OpenAPI에 해당 라우트가 노출되면 기계
    정본도 자동 확보된다.
- **TA-03 🟡 — export 노출 정책 확정 반영** ✅ D-05 **(a) 확정 (2026-06-10, krtour ADR-050 #3)** — 검수 통과만 export
  - 권고안: 검수 통과(`matched`/`user_corrected`)만 export. `needs_review`/`ignored`
    제외를 export 쿼리 명세에 **명문화** (현재 plan 문서에 노출 기준이 암묵적).
  - 검수 후 철회 시 `reject` operation을 증분으로 내보내는 흐름도 함께 명세.
- **TA-04 🟡 — RustFS 버킷 소유권** (의사결정 D-01)
  - 현재 `RUSTFS_BUCKET_RAW_VIDEOS/SUBTITLES/FRAMES` 기본값이 모두 **krtour-map 소유
    버킷명 `krtour-map`** (prefix `features/`)이다. krtour의 백업/수명주기 책임과 충돌
    소지가 있어 cross-repo 검토에서 "전용 버킷 분리(권고)" vs "공유+정책 명문화"가
    의사결정에 올라갔다.
  - ✅ D-01 **결정 (2026-06-10, krtour ADR-052)**: **당분간 공유 유지 + prefix 소유권/
    backup 제외 명문화, 추후 전용 버킷 분리**. 분리 시점도 확정(D-10, 2026-06-10 2차):
    **T-066 운영 개시(krtour-map 실데이터 pull 시작) 전 분리** — 운영 데이터가 쌓이기
    전이 마이그레이션 비용 최소. 분리 주체는 본 repo(버킷 config + 객체 이전),
    krtour-map은 backup 정책 갱신만. **즉 T-066 일정에 버킷 분리를 선행 단계로 포함할 것.**
- **TA-05 🟡 — category 매핑 정본 고정** (T-065 연계)
  - `category_code_suggestion`(8자리)의 유효값 정본은 krtour-map `GET /v1/categories`
    (포트 9011)다. 매핑 테이블을 본 repo에 복제하지 말고, 코드 목록은 category API/문서를
    참조하고 본 repo는 "추출 라벨 → 코드 제안" 규칙만 보유한다. 미확정 시
    `category_code_suggestion: null` + `category_label`만 보내면 krtour 변환부가
    fallback(`01010000` TOURISM)을 적용한다.

## 3. 참고 — 상대 시스템에서 진행되는 짝 작업

- **krtour-map**: reject/tombstone skip → feature inactive 전환 구현 검토(D-03, KR-01),
  T-066 완료 후 Dagster live fetch smoke(KR-08), evidence(영상 링크·confidence)의
  feature detail 노출 형태 확정(KR-06).
- **TripMate**: YouTube 발 feature에 출처 배지+영상 링크 UX(TM-08) — 본 repo가 export에
  싣는 `youtube.video_url`/`evidence.timestamp_*`/`confidence_score`가 최종 사용자
  화면까지 전달되는 사슬의 시작점이므로, TA-01 구현 시 이 필드들의 누락/축약에 주의.

## 4. 문서 상태 평가 (본 repo)

이번 교차 검토에서 tripmate-agent 문서는 세 repo 중 **일관성 최상** 평가
(README/CLAUDE/AGENTS/architecture/decisions/tasks가 2026-06-10 기준 정렬, 충돌 0건).
보완 필요는 위 TA-02(계약 정본 독립)와 TripMate 소비 계약 상세(T-068 범위) 두 가지다.
