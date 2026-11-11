"use client";

import { useMemo, useState, useSyncExternalStore } from "react";
import {
  createPersistedStateStore,
  type StorageStatePort,
} from "./persisted-state-store";

const STORAGE_CHANGED = "ktc:persisted-state";
type StorageKind = "session" | "local";

function browserStoragePort(key: string, kind: StorageKind): StorageStatePort {
  const storage = () =>
    kind === "local" ? window.localStorage : window.sessionStorage;
  return {
    read: () => storage().getItem(key),
    write: (value) => storage().setItem(key, value),
    publish: () =>
      window.dispatchEvent(
        new CustomEvent(STORAGE_CHANGED, { detail: { key, kind } }),
      ),
    subscribe(listener) {
      const onStorage = (event: StorageEvent) => {
        if (event.key == null || event.key === key) listener();
      };
      const onLocal = (event: Event) => {
        const detail = (
          event as CustomEvent<{ key: string; kind: StorageKind }>
        ).detail;
        if (detail?.key === key && detail.kind === kind) listener();
      };
      window.addEventListener("storage", onStorage);
      window.addEventListener(STORAGE_CHANGED, onLocal);
      return () => {
        window.removeEventListener("storage", onStorage);
        window.removeEventListener(STORAGE_CHANGED, onLocal);
      };
    },
  };
}

/** SSR은 initial, hydration 뒤에는 저장소 snapshot을 구독하며 같은 탭의 소비자도 동기화한다. */
export function usePersistedState<T>(
  key: string,
  initial: T,
  kind: StorageKind = "session",
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [seed] = useState(() => ({ initial }));
  const store = useMemo(
    () =>
      createPersistedStateStore(seed.initial, browserStoragePort(key, kind)),
    [key, kind, seed],
  );
  const value = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getServerSnapshot,
  );
  return [value, store.setValue];
}
