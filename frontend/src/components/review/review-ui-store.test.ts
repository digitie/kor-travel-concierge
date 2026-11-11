import { describe, expect, it } from "vitest";
import { createReviewUiStore } from "./review-ui-store";
describe("검수 UI의 일관된 상태 구독", () => {
  it("후보와 편집 폼을 한 snapshot으로 알린다", () => {
    const ui = createReviewUiStore<number, string>();
    const observed: Array<{ id: number | null; name: string }> = [];
    const unsubscribe = ui.store.subscribe((state) =>
      observed.push({ id: state.selectedId, name: state.form.name }),
    );
    ui.batch(() => {
      ui.actions.setSelectedId(7);
      ui.actions.setForm((current) => ({ ...current, name: "일곱 번째 후보" }));
      ui.actions.setFormCandidateId(7);
    });
    expect(observed).toEqual([{ id: 7, name: "일곱 번째 후보" }]);
    expect(ui.store.getState().formCandidateId).toBe(7);
    unsubscribe();
  });
  it("중첩 전이의 함수형 갱신은 직전 draft를 보고 한 번만 알린다", () => {
    const ui = createReviewUiStore<number, string>();
    let updates = 0;
    ui.store.subscribe(() => updates++);
    ui.batch(() => {
      ui.actions.setSelectedCandidateIds([1]);
      ui.batch(() => ui.actions.setSelectedCandidateIds((ids) => [...ids, 2]));
      ui.actions.setSelectedCandidateIds((ids) => [...ids, 3]);
    });
    expect(ui.store.getState().selectedCandidateIds).toEqual([1, 2, 3]);
    expect(updates).toBe(1);
  });
  it("SSR/화면 인스턴스 사이에 후보·좌표·확정 상태를 공유하지 않는다", () => {
    const first = createReviewUiStore<number, string>(),
      second = createReviewUiStore<number, string>();
    first.actions.setSelectedId(99);
    first.actions.setForm((current) => ({
      ...current,
      latitude: "37",
      longitude: "127",
    }));
    expect(second.store.getState().selectedId).toBeNull();
    expect(second.store.getState().form.latitude).toBe("");
  });
});
