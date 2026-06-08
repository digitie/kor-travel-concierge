# PR 상세 리뷰 종합 (2026-06-08)

이 문서는 PR #1 ~ #29 전체에 대한 상세 리뷰 결과와, 리뷰에서 도출된 후속 조치(TODO)를 **긴급성 순서**로 정리한 것이다. 각 PR에는 개별 리뷰 코멘트가 게시되어 있으며, 이 문서는 그 코멘트들을 교차 정리한 상위 요약이다.

리뷰는 두 차례로 진행되었다.

1. **1차 (PR #1 ~ #19)**: 각 PR diff를 프로젝트 규칙(`AGENTS.md`, ADR, DO-NOT)에 비춰 검토.
2. **2차 (PR #20 ~ #29)**: 신규 PR 검토. 이 중 #21 ~ #24는 1차 리뷰 지적을 반영한 PR이라, **지적 사항이 실제로 해소되었는지 검증**하는 방식으로 리뷰.

> 모든 PR이 이미 머지된 상태이므로, 아래 TODO는 머지 게이트가 아니라 **후속 PR 기준**의 작업 목록이다.

---

## 1. 리뷰 반영 PR의 해소 현황 요약

1차 리뷰 지적은 #21 ~ #24에서 대부분 해소되었다. 핵심 미해소 항목만 P0/P1으로 아래에 올렸다.

| 반영 PR | 대상 | 해소 | 부분 | 미해소 |
|---------|------|:----:|:----:|:------:|
| #21 (문서/기획 #1–5) | maplibre 패키지명, CORS, MCP 기본값, ADR-9/11 모순, env 누락, mcp 네임스페이스 등 | 9 | 0 | 0 |
| #22 (백엔드·MCP·스케줄러 #6/12/14) | settings 검증, StrEnum, claim 원자성, merge_places, 멱등성 등 | 9 | 1 | 1 |
| #23 (ETL·동영상·지오코딩 #8/9/10/11/13/17) | 키 노출, quota, watermark, 이벤트 루프, geom NULL, fallback 등 | 21 | 0 | 1 |
| #24 (프론트·E2E·문서 #15/16/18/19) | Tailwind 문법, RHF+Zod, datetime.UTC, ADR 트리거 등 | 10 | 1 | 1 |

전체적으로 **보안·정합성 핵심 결함은 정확히 수정**되었고, 회귀는 거의 발견되지 않았다. 남은 항목은 아래 우선순위 목록으로 추적한다.

---

## 2. 긴급성 순 TODO

### 🔴 P0 — Blocker (런타임/배포에서 기능이 깨짐, 최우선)

- [x] **P0-1. Tailwind 색상 토큰 alpha 미지원 — 투명도 modifier 전부 무효** (`#15(b)`, #24에서 미해소, T-034에서 후속 해소)
  - 근거: `frontend/src/app/globals.css` / `frontend/tailwind.config.ts`의 색상 토큰이 alpha 채널 없는 bare `var(--x)`(oklch). 프로젝트 자체 Tailwind v3.4 CLI로 컴파일 검증 결과 `bg-destructive/10`, `ring-ring/50`, `bg-muted/70`, `bg-muted/50` 등이 **CSS를 0바이트 출력**(조용히 누락).
  - 영향: 포커스 링, invalid 링, destructive 배경 틴트, #24가 새로 추가한 `VWorldMap.tsx`의 `bg-muted/70` fallback 오버레이까지 렌더링 안 됨. `build`는 통과해 가려짐.
  - 조치: 토큰을 alpha 주입 가능한 형태로 재정의(예: `hsl(var(--x) / <alpha-value>)` 또는 v3 호환 채널 분리). 누락 중인 `--destructive-foreground` 정의도 함께 보강.
  - 후속 처리: T-034에서 Tailwind 색상 토큰을 alpha-aware 함수형 토큰으로 전환하고 `--destructive-foreground` 누락을 보강했다. Tailwind CLI 산출물에서 주요 alpha class 생성을 확인하고 frontend lint/type-check/build 및 Playwright E2E를 통과했다.

- [x] **P0-2. `deep_research` job 핸들러 미등록 — MCP `trigger_deep_research`가 즉시 실패** (`#14`, #22에서 미해소, T-035에서 후속 해소)
  - 근거: `scheduler/worker.py`의 `DEFAULT_HANDLERS`가 `{"harvest"}`만 등록. `trigger_deep_research`는 `job_type="deep_research"` crawl_run을 만들고 MCP 도구로 노출되는데, 스케줄러가 "지원하지 않는 job_type"으로 곧바로 `mark_failed` 처리.
  - 조치: `deep_research` 핸들러를 등록하거나, 핸들러가 없을 때의 동작(보류/명시적 오류)을 정의.
  - 후속 처리: T-035에서 `deep_research` 기본 handler와 `deep_research_service`를 추가해 장소 상세 조사 결과를 `travel_places.detailed_research_content`에 저장하도록 연결했다. 기본 scheduler 실행에서 `deep_research` 작업이 `done`으로 완료되는 테스트를 보강했다.

- [x] **P0-3. 기존 DB의 stale unique index — 반복 등장 저장이 IntegrityError** (`#27`, `#22`, T-036에서 후속 해소)
  - 근거: 모델에서 `UniqueConstraint("video_id","place_id")`를 제거했으나 `init_db()`는 `create_all`만 호출(Alembic 부재). `create_all`은 기존 인덱스를 DROP하지 못하므로, 이미 기동된 SQLite에는 `uq_video_place_mappings_video_place`가 남아 같은 영상의 같은 장소를 두 번째 매핑할 때 IntegrityError 발생 → #27의 핵심(반복 등장 보존·`mention_count`)이 기존 환경에서 깨짐. `merge_places`가 같은 `video_id`를 재배정할 때도 동일 충돌(#22).
  - 조치: 기존 `ensure_*_columns` 패턴처럼 init 경로에 `DROP INDEX IF EXISTS uq_video_place_mappings_video_place` 추가. 테스트는 매번 새 DB라 이 드리프트를 못 잡으므로 마이그레이션 경로 테스트 보강 권장. (DO-NOT #5)
  - 후속 처리: T-036에서 명시 unique index 제거와 table-level legacy unique constraint 테이블 재생성 경로를 `init_db()`에 추가했다. legacy table 재생성 후 같은 영상·장소 반복 매핑 insert가 가능한 테스트를 보강했다.

### 🟠 P1 — Major (데이터 정합성 / 보안 강화 / 운영 안정성)

- [x] **P1-1. `store_raw_media` 전체 동영상 메모리 적재(OOM)** (`#11`, #23에서 docstring만 추가, T-037에서 후속 해소)
  - 무기한 보존 대상 원본 동영상(수백 MB+)을 `bytes`로 통째 메모리 적재 후 업로드. 멀티파트/스트리밍 업로드 경로 필요.
  - 후속 처리: T-037에서 `store_raw_media`에 file-like streaming 경로를 추가하고, RustFS 업로드는 `upload_fileobj`로 전송하도록 보강했다. 업로드 중 SHA256과 크기를 계산해 `media_assets`에 기록하는 테스트를 추가했다.

- [x] **P1-2. `claim_next_pending` 비원자적 claim** (`#12`, #22에서 부분 해소, T-038에서 후속 해소)
  - `busy_timeout=5000`은 추가됐으나 여전히 SELECT-후-mutate 구조이고 쓰기 시 `WHERE state='pending'` 가드가 없음. 단일 실행자 불변식에만 의존. 가드 있는 UPDATE로 진짜 원자적 claim 권장.
  - 후속 처리: T-038에서 후보 id 조회 후 `UPDATE ... WHERE id=:id AND state='pending' RETURNING id`로 claim을 확정하도록 바꿨다. 파일 기반 SQLite 병렬 claim 테스트를 추가했다.

- [x] **P1-3. 스키마 드리프트 전반 — Alembic 부재** (`#22`, `#27` 공통, T-039에서 후속 해소)
  - `create_all`은 기존 SQLite에 신규 제약/`BigInteger`/non-null 컬럼을 ALTER하지 못함. 신규 DB에서만 반영됨. 경량 마이그레이션 체계(또는 명시적 init 보정 스크립트) 도입 검토. (DO-NOT #5)
  - 후속 처리: T-039에서 `schema_migrations` 테이블과 `run_schema_migrations`를 추가해 init 보정 작업의 적용 이력을 추적하도록 했다. 현재 보정 migration은 `crawl_runs` 상태 로그 컬럼과 `video_place_mappings` 반복 등장 제약 제거를 관리한다.

- [x] **P1-4. 지도 marker 전량 재생성 + 강제 재중심** (`#16(b)`, #24에서 부분 해소, T-040에서 후속 해소)
  - `easeTo`는 별도 effect로 분리됐으나, 선택 변경 시 marker를 여전히 전량 teardown·재생성하고 실제 데이터 변경 시 사용자가 패닝한 지도를 재중심. diff 기반 marker 캐싱 + 선택 클릭에서만 `easeTo` 권장.
  - 후속 처리: T-040에서 marker를 `place_id` 기준 cache로 관리해 기존 marker를 갱신·추가·삭제하고, 선택 스타일 동기화와 선택 장소 재중심을 분리했다. 장소 데이터 refresh는 marker 위치와 popup만 갱신하고 지도 재중심을 유발하지 않는다.

- [x] **P1-5. FFmpeg 자동 다운로드 무결성 미검증 + 취약한 고정 URL** (`#29`, T-041에서 후속 해소)
  - `ensure-windows-ffmpeg.ps1`이 `.7z`/`7zr.exe`를 SHA256 검증 없이 받아 실행(공급망 갭). 또한 날짜 고정 gyan.dev URL은 추후 404 → `start-windows-live.ps1` 시작이 throw. `Get-FileHash` 검증 + `release/ffmpeg-release-full.7z` 안정 URL(또는 갱신 주기 명문화) 권장.
  - 후속 처리: T-041에서 기본 FFmpeg URL을 gyan.dev 안정 링크 `ffmpeg-release-full.7z`로 전환하고 `.sha256` sidecar 또는 명시 hash 검증을 통과한 아카이브만 압축 해제하도록 보강했다. portable `7zr.exe`도 버전 고정 GitHub asset과 고정 SHA256으로 검증한다.

- [x] **P1-6. docker-compose CORS 하드코딩 / 포트 점유 프로세스 무확인 강제 종료** (`#26`, T-042에서 후속 해소)
  - `docker-compose.yml`이 CORS를 하드코딩해 `.env`의 `CORS_ALLOW_ORIGINS` override가 단절되고 `3000`/`13000` origin 누락. `Stop-PortOwner`가 9041/9042 점유 임의 프로세스를 경고 없이 `Stop-Process -Force` → 확인 절차 추가 권장.
  - 후속 처리: T-042에서 Compose CORS가 `.env` override를 우선하고 기본 origin에 Web host port(`9042` 또는 `FRONTEND_HOST_PORT` override), `3000`, `13000`, `13100`을 포함하도록 수정했다. Windows live 스크립트는 현재 워크트리 프로세스로 확인되는 포트 점유자만 자동 종료하고, 다른 프로세스는 `-ForcePortKill` 명시가 필요하다.

### 🟡 P2 — Minor (정확성 / 품질 / 일관성)

- [x] **P2-1. export 직렬화가 이벤트 루프 블로킹 + 상한 부재 + XML 제어문자 미정제** (`#27`, T-043에서 후속 해소) — executor 격리, limit 상한, xlsx/GPX/KML의 XML 1.0 불법 제어문자 정제.
  - 후속 처리: T-043에서 export 조회 상한을 기본 500건·최대 1,000건으로 제한하고, XLSX/GPX/KML 직렬화를 `asyncio.to_thread`로 격리했다. XML 텍스트는 XML 1.0 유효 문자만 남긴 뒤 escape하며, API thread 실행·limit clamp와 XML sanitizer 테스트를 추가했다.
- [x] **P2-2. 증분 수집 미완** (`#23`, T-044에서 후속 해소) — keyword 검색·playlist harvest 경로가 매 실행 full-rescan(`publishedAfter`/watermark 미적용). 현재는 quota cap으로만 완화됨.
  - 후속 처리: T-044에서 keyword harvest는 `source_targets.last_crawled_at`을 YouTube `search.list`의 `publishedAfter`로 전달하고, playlist harvest는 영상 공개 시각이 target watermark 이하가 되면 pagination을 중단하도록 보강했다. 수집 성공 후 source target crawl 시각도 갱신한다.
- [x] **P2-3. `next-env.d.ts` 생성물 추적 + 훅 정규화 의존** (`#25`, T-045에서 후속 해소) — gitignore + `git rm --cached`로 흔들림 원천 제거 권장(미채택 시 추적 유지 근거를 ADR로).
  - 후속 처리: T-045에서 `frontend/next-env.d.ts`를 git index에서 제거하고 `.gitignore`에 추가했다. 정규화용 `normalize-next-env.mjs`와 `posttype-check`/`postbuild` hook도 제거해 생성물 흔들림을 추적 상태에서 원천 차단했다.
- [x] **P2-4. Next 16 후속 정리** (`#20`, T-046에서 후속 해소) — `tsconfig` `jsx`는 Next 권장 `preserve`로, `@types/node`는 런타임(20.9+)에 맞춰 `^20`/`^22`로, `engines: {node: ">=20.9.0"}` 추가.
  - 후속 처리: T-046에서 `engines.node >=20.9.0`을 추가하고 `@types/node`를 `^20` 계열로 낮춰 lockfile을 갱신했다. `jsx: preserve`는 `next typegen`이 Next.js 16.2.7 mandatory change로 `react-jsx`를 재적용해 현재 도구 강제값을 유지했다.
- [x] **P2-5. `suppressHydrationWarning` 범위 과다 + vworld 키 중복 주입** (`#28`, T-047에서 후속 해소) — 공유 `Input`의 전역 suppress는 실제 SSR 버그까지 가림. 자식 프로세스 명령줄 키 재주입 제거(상속만 사용).
  - 후속 처리: T-047에서 공유 `Input`의 전역 `suppressHydrationWarning`을 제거했다. Windows live 스크립트는 `.env`에서 읽은 VWorld 키를 부모 PowerShell 환경에만 설정하고 frontend child 명령 블록에는 재주입하지 않도록 정리했다. E2E frontend 시작 스크립트도 VWorld 키 fallback 기본값을 부모 프로세스에만 설정한 뒤 child는 상속 환경을 사용한다.
- [ ] **P2-6. heartbeat의 `contextlib.suppress(...Exception)`** (`#22`) — 하트비트 await의 모든 예외 삼킴. 좁히기.
- [ ] **P2-7. engine 모델 설정의 단일 출처 부재** (`#28`) — frontend zod enum / backend `set_setting`(키만 검증) / `.env.example`·`config.py` 기본값이 제각각.
- [ ] **P2-8. `_names_compatible` 부분일치 관대함** (`#23`) — 짧은 이름에서 false-positive 재사용 가능.

### 🔵 P3 — Nit / 제안

- [ ] **P3-1.** 문서 상태 불일치 잔존(예: 일부 `CLAUDE.md` ↔ `tasks.md` 작업 상태) 정리.
- [ ] **P3-2.** `FFPROBE_PATH`가 config/.env/compose에 추가됐으나 백엔드 코드 미사용; frontend compose 서비스에 ffmpeg env 불필요 주입(#29).
- [ ] **P3-3.** export 파일명 고정(`tripmate-places.*`) → 타임스탬프/필터 반영(#27).
- [ ] **P3-4.** import 정렬, FK `ondelete` 명시, `TimestampMixin` 일관성 등 코드 위생(#7 외).
- [ ] **P3-5.** `& py -3.10` 마이너 고정은 3.11/3.12-only 호스트에서 폴백 실패(정책은 "3.10+")(#26).

---

## 3. 반복된 횡단 주제 (설계 차원에서 한 번에 처리 권장)

1. **스키마 마이그레이션 부재(Alembic 없음)** — `create_all` 한계로 기존 DB에 변경이 반영되지 않음. P0-3 / P1-3의 근본 원인. (DO-NOT #5)
2. **SQLite 비동기·단일 실행자 가정의 취약성** — 비원자적 claim, FK 강제 의존, 트랜잭션 경계. 대부분 #22에서 개선됐으나 claim 원자성은 잔존(P1-2).
3. **SpatiaLite geom 채움 일관성** — 1차에서 반복 지적되던 geom NULL은 #23에서 해소(`sync_place_geometry` 호출). 신규 장소 생성 경로 추가 시 동일 호출 누락 주의.
4. **외부 바이너리/네트워크 의존의 견고성** — FFmpeg 다운로드 무결성/URL, 라이브 스타트업 readiness 폴링 등 Windows 라이브 경로의 운영 견고성(P1-5, P2 일부).

---

## 4. 개별 PR 리뷰 코멘트 색인

각 PR의 상세 리뷰는 해당 PR 코멘트를 참고한다.

- #1 ~ #5: 기획/문서 정합성 (언어 정책, ADR supersede, env 매핑, mcp 네임스페이스)
- #6 ~ #13: 백엔드 기반·공간 모델·YouTube 수집·자막/POI·지오코딩·프레임·스케줄러·harvest
- #14 ~ #19: MCP 도구·프론트 스택·지도/패널·Compose·E2E·ADR-20
- #20 ~ #24: Next 16 업그레이드 및 1차 리뷰 반영(#21–24 검증 리뷰)
- #25 ~ #29: route 타입 안정화·라이브 포트 고정·장소 언급 소스/export·라이브 후속 보완·FFmpeg/지도 안정화
