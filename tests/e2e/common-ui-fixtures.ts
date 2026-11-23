// common-ui·mobile-ui spec이 함께 쓰는 격리 API 목과 로그인. 실제 백엔드 없이 BFF 앞단만 가로챈다.
import { expect, type Page } from "@playwright/test";
import type { CrawlRunSummary, DestinationSummary, UnmatchedCandidate } from "../../frontend/src/lib/api";

export const run: CrawlRunSummary = {
  job_id: "common-ui-run", job_type: "harvest", source: "keyword",
  target_type: "keyword", target_id: "서울", target_label: "공통 검증 검색",
  state: "done", progress: 1, current_message: "완료", status_logs: [], retry_count: 0,
  last_error: null, restart_of_run_id: null, attention: null, result: {},
  created_at: "2026-11-11T00:00:00Z", started_at: null, finished_at: null,
};
export const candidates: UnmatchedCandidate[] = [1, 2].map(id => ({
  id, video_id: "sample-video-" + id, video_title: "검증 영상 " + id, channel_title: "검증 채널",
  ai_place_name: "검증 장소 " + id, location_hint: null, candidate_category: null,
  candidate_category_code: null, match_status: "needs_review", review_state: "needs_review",
  state_revision: 1, last_client_operation_id: null, video_is_excluded: false,
  confidence_score: 0.8, source_kind: "transcript", grounding_status: "missing",
  created_at: "2026-11-11T00:00:00Z", queue_reason: "no_result", timestamp_start: null,
  is_domestic: true,
}));
export const places: DestinationSummary[] = [1, 2].map(number => ({
  place_id: 10 + number, name: "키 없는 지도 검증 장소 " + number,
  description: null, gemini_enriched_description: null,
  latitude: 37.55 + number / 100, longitude: 126.97 + number / 100,
  category: null, official_address: null, road_address: null, is_geocoded: true,
  mention_count: 1, source_channel_count: 1, source_videos: [],
}));
export function envelope(items: unknown[]) {
  return { items, next_cursor: null, has_more: false, total: items.length, newest_id: 2, newer_than: 0 };
}
export async function mockApi(page: Page) {
  const calls: string[] = [];
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    calls.push(request.method() + " " + pathname);
    let data: unknown = [];
    if (pathname === "/api/v1/runs/queue") data = { items: [], running_count: 0, pending_count: 0, open_attention_count: 0, has_more: false, user_job_types: ["harvest"] };
    else if (pathname === "/api/v1/runs") data = envelope([run]);
    else if (pathname === "/api/v1/runs/one-time-harvest") data = { items: [run] };
    else if (pathname === "/api/v1/runs/common-ui-run") data = run;
    else if (pathname.endsWith("/places")) data = [{ kind: "candidate", place_id: null, candidate_id: 1, name: "검증 추출 장소", status: "needs_review", is_domestic: true }];
    else if (pathname.endsWith("/videos")) data = [{ video_id: "sample-video", title: "공통 수집 영상", url: "https://www.youtube.com/watch?v=sample-video", channel_title: "검증 채널", duration_seconds: 60, published_at: "2026-11-11T00:00:00Z" }];
    else if (pathname === "/api/v1/source-targets") data = [{ id: 1, target_type: "keyword", source_value: "서울", display_name: "공통 반복 대상", is_active: true, scan_interval_minutes: 60, max_runs: 0, max_videos: 3, default_category_code: null, default_category_label: null, run_count: 1, next_crawl_at: null, last_crawled_at: null, last_scan_at: null, last_seen_video_published_at: null, scan_failure_count: 0, last_scan_error: null, created_at: null }];
    else if (pathname.endsWith("/video-stats")) data = [{ video_id: "sample-video", title: "공통 검증 영상", url: "https://www.youtube.com/watch?v=sample-video", poi_auto: 1, poi_needs_review: 1, poi_resolved: 0, poi_total: 2 }];
    else if (pathname.endsWith("/transcript")) data = { text: "공통 확장행 자막입니다.", source: "test", segments: [] };
    else if (pathname === "/api/v1/destinations/reprocess") data = { enqueued_jobs: 1, videos: 1, job_ids: ["reprocess-test"], start_stage: "transcript" };
    else if (pathname === "/api/v1/place-search") data = { query: new URL(request.url()).searchParams.get("q") ?? "", searched_at: "2026-11-11T00:00:00Z", google: [], kakao: [], naver: [], errors: {} };
    else if (pathname === "/api/v1/destinations") data = envelope(places);
    else if (/\/destinations\/\d+\/detail$/.test(pathname)) {
      await route.fulfill({ status: 503, json: { detail: "격리 검증의 장소 상세 오류" } });
      return;
    }
    else if (pathname === "/api/v1/destinations/unmatched") data = envelope(candidates);
    else if (pathname.includes("facets")) data = { channels: [], playlists: [], keywords: [] };
    else if (/\/destinations\/unmatched\/\d+/.test(pathname)) {
      await route.fulfill({ status: 503, json: { detail: "격리 검증에서 상세 공급은 사용하지 않습니다." } });
      return;
    }
    await route.fulfill({ json: data });
  });
  return calls;
}
export async function login(page: Page, next: string) {
  await page.goto("/login?next=" + encodeURIComponent(next));
  await page.locator("[data-slot=login-password]").fill(process.env.KTC_COMMON_UI_TEST_PASSWORD!);
  await page.locator("[data-slot=login-username]").fill("test-operator");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe(next);
}
