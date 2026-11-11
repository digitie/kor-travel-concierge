import { describe, expect, it } from "vitest";
import { createMapCameraStore } from "./map-camera";

describe("선택 시에만 고정하는 지도 카메라", () => {
  it("같은 선택에서 사용자가 축소해도 카메라를 다시 확대한 목표로 교체하지 않는다", () => {
    const camera = createMapCameraStore(6.2, 12);
    camera.focus(1, 0, [127, 37]);
    const target = camera.store.getState().target;
    camera.trackZoom(8);
    camera.focus(1, 0, [127, 37]);
    expect(camera.store.getState().target).toBe(target);
    expect(camera.store.getState().zoom).toBe(8);
  });
  it("장소·좌표·재중심 key 변경은 현재 줌을 반영하고 줌 이벤트만으로 목표를 바꾸지 않는다", () => {
    const camera = createMapCameraStore(6.2, 12);
    camera.trackZoom(14);
    camera.focus(1, 0, [127, 37]);
    expect(camera.store.getState().target?.zoom).toBe(14);
    const first = camera.store.getState().target;
    camera.trackZoom(7);
    expect(camera.store.getState().target).toBe(first);
    camera.focus(1, 1, [127, 37]);
    expect(camera.store.getState().target?.zoom).toBeGreaterThan(12);
    camera.focus(1, 1, [128, 38]);
    expect(camera.store.getState().target?.center).toEqual([128, 38]);
    camera.focus(2, 1, [128, 38]);
    expect(camera.store.getState().signature).toContain("2");
  });
  it("지도 인스턴스끼리 선택과 줌을 공유하지 않는다", () => {
    const first = createMapCameraStore(6, 12);
    const second = createMapCameraStore(6, 12);
    first.trackZoom(15);
    first.focus(1, 0, [127, 37]);
    expect(second.store.getState()).toEqual({ zoom: 6, target: undefined, signature: null });
  });
});
