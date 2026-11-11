import { createStore } from "zustand/vanilla";

type CameraTarget = { center: [number, number]; zoom: number };
type CameraState = { zoom: number; signature: string | null; target: CameraTarget | undefined };

/** 줌 이벤트는 저장만 하고 선택 대상이 바뀔 때 카메라 목표를 한 번 고정한다. */
export function createMapCameraStore(initialZoom: number, focusZoom: number) {
  const store = createStore<CameraState>(() => ({ zoom: initialZoom, signature: null, target: undefined }));
  return {
    store,
    trackZoom(zoom: number) {
      if (Number.isFinite(zoom)) store.setState({ zoom });
    },
    focus(placeId: number, focusKey: number, center: [number, number]) {
      const signature = JSON.stringify([placeId, focusKey, ...center]);
      const current = store.getState();
      if (signature === current.signature) return;
      store.setState({
        signature,
        target: { center, zoom: Math.max(current.zoom, focusZoom) + focusKey * 1e-9 },
      });
    },
  };
}
