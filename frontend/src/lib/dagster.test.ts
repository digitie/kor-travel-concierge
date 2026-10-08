import { describe, expect, it } from "vitest";
import { parseHealthyDagsterSummary } from "./dagster";
const healthy = () => ({ status: "ok", publicUrl: "https://dagster.example.invalid", error: null,
  snapshot: { checkedAt: "2026-10-08T00:00:00Z", runs: [], repositories: [] } });
describe("Dagster 응답을 교체하기 전 검증", () => {
  it("정상 빈 snapshot을 허용한다", () => expect(parseHealthyDagsterSummary(healthy()).snapshot.runs).toEqual([]));
  it.each([null, undefined, 42, "javascript:alert(1)"])("유효하지 않은 publicUrl을 거절한다 %s", value => {
    expect(() => parseHealthyDagsterSummary({ ...healthy(), publicUrl: value })).toThrow();
  });
  it.each([undefined, null, {}, [null]])("잘못된 runs를 거절한다 %s", runs => {
    expect(() => parseHealthyDagsterSummary({ ...healthy(), snapshot: { ...healthy().snapshot, runs } })).toThrow();
  });
  it("nested repository 배열과 상태를 검증한다", () => {
    expect(() => parseHealthyDagsterSummary({ ...healthy(), snapshot: { ...healthy().snapshot, repositories: [{ name: "ktc", locationName: "ktc", jobs: null, assets: [], schedules: [] }] } })).toThrow();
    expect(() => parseHealthyDagsterSummary({ ...healthy(), status: "degraded" })).toThrow();
  });
});
