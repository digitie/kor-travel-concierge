// @vitest-environment jsdom

import { act, createElement, useState } from "react";
import { createRoot } from "react-dom/client";
import userEvent from "@testing-library/user-event";
import { afterAll, describe, expect, it, vi } from "vitest";

import type { UnmatchedCandidate } from "@/lib/api";
import { CandidateTable } from "./CandidateTable";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
afterAll(() => vi.unstubAllGlobals());

const candidate: UnmatchedCandidate = {
  id: 1, video_id: "focus-video", video_title: "검증 영상", channel_title: "검증 채널",
  ai_place_name: "키보드 후보", location_hint: null, candidate_category: null,
  candidate_category_code: null, match_status: "needs_review", review_state: "needs_review",
  state_revision: 1, last_client_operation_id: null, video_is_excluded: false,
  confidence_score: 0.8, source_kind: "transcript", grounding_status: "missing",
  created_at: "2026-11-11T00:00:00Z", queue_reason: "no_result", timestamp_start: null,
  is_domestic: true,
};
const candidates = [candidate];
const selectable = new Set([1]);
const cart = new Set<string>();

describe("CandidateTable 키보드 선택", () => {
  it.each(["불러온 후보 전체 선택", "키보드 후보 후보 선택"])(
    "%s: Space로 선택·해제해도 같은 DOM과 포커스를 유지한다",
    async (name) => {
      const onPick = vi.fn();
      function Harness() {
        const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
        const toggle = () => setSelected(previous => previous.has(1) ? new Set() : new Set([1]));
        return createElement(CandidateTable, {
          candidates, currentCandidateId: null, selectedCandidateIds: selected,
          cartVideoIds: cart, bulkSelectableCandidateIds: selectable,
          allLoadedCandidatesSelected: selected.has(1), someLoadedCandidatesSelected: selected.has(1),
          bulkSelectionLimitReached: false, candidateActionPending: false, removedMode: false,
          isCandidateActionable: () => true,
          onToggleAllLoadedCandidates: toggle, onToggleSelect: toggle, onPick,
          onToggleCart: vi.fn(), onOpenDetail: vi.fn(), onRequestDelete: vi.fn(), onRestore: vi.fn(),
        });
      }
      const container = document.createElement("div");
      document.body.append(container);
      const root = createRoot(container);
      const user = userEvent.setup();
      try {
        await act(async () => root.render(createElement(Harness)));
        const checkbox = container.querySelector<HTMLElement>('[role="checkbox"][aria-label="' + name + '"]')!;
        checkbox.focus();
        expect(document.activeElement).toBe(checkbox);
        for (const checked of ["true", "false"]) {
          await act(async () => user.keyboard("[Space]"));
          const current = container.querySelector('[role="checkbox"][aria-label="' + name + '"]');
          expect(current?.getAttribute("aria-checked")).toBe(checked);
          expect(current).toBe(checkbox);
          expect(checkbox.isConnected).toBe(true);
          expect(document.activeElement).toBe(checkbox);
        }
        expect(onPick).not.toHaveBeenCalled();
        expect(candidates[0]).toBe(candidate);
      } finally {
        await act(async () => root.unmount());
        container.remove();
      }
    },
  );
});
