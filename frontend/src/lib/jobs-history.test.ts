import { describe, expect, it } from "vitest";

import { buildRunHistoryParams } from "@/lib/jobs-history";

describe("buildRunHistoryParams", () => {
  it("기본(전체) 필터는 terminal + user_jobs_only를 소비한다", () => {
    expect(
      buildRunHistoryParams({ attentionOnly: false, state: "all", jobType: "all" }),
    ).toEqual({ terminal: true, userJobsOnly: true });
  });

  it("attention 필터는 open을 전달한다", () => {
    expect(
      buildRunHistoryParams({ attentionOnly: true, state: "all", jobType: "all" }),
    ).toEqual({ terminal: true, userJobsOnly: true, attention: "open" });
  });

  it("특정 유형은 job_types로 전환하고 user_jobs_only를 함께 쓰지 않는다", () => {
    const params = buildRunHistoryParams({
      attentionOnly: false,
      state: "all",
      jobType: "harvest",
    });
    expect(params).toEqual({ terminal: true, jobTypes: ["harvest"] });
    expect(params.userJobsOnly).toBeUndefined();
  });

  it("종료 상태 필터를 state로 전달한다", () => {
    expect(
      buildRunHistoryParams({ attentionOnly: false, state: "failed", jobType: "all" }),
    ).toEqual({ terminal: true, userJobsOnly: true, state: "failed" });
  });

  it("유형 + 상태 + attention을 함께 소비한다", () => {
    expect(
      buildRunHistoryParams({
        attentionOnly: true,
        state: "done",
        jobType: "poi_batch",
      }),
    ).toEqual({
      terminal: true,
      attention: "open",
      state: "done",
      jobTypes: ["poi_batch"],
    });
  });
});
