import type { SetStateAction } from "react";

export type StorageStatePort = {
  read: () => string | null;
  write: (value: string) => void;
  subscribe: (listener: () => void) => () => void;
  publish: () => void;
};

/** 저장값을 읽기 전에 초기값을 쓰지 않으며, 동일 원문에는 동일 snapshot을 반환한다. */
export function createPersistedStateStore<T>(
  initial: T,
  port: StorageStatePort,
) {
  let value = initial;
  let lastRaw: string | null | undefined;
  let memoryOnly = false;
  const listeners = new Set<() => void>();
  function getSnapshot(): T {
    if (memoryOnly) return value;
    try {
      const raw = port.read();
      if (raw !== lastRaw) {
        lastRaw = raw;
        value = raw == null ? initial : (JSON.parse(raw) as T);
      }
    } catch {
      // 손상된 저장값이나 차단된 저장소는 마지막 정상 snapshot을 유지한다.
    }
    return value;
  }
  function setValue(action: SetStateAction<T>) {
    const previous = getSnapshot();
    const next =
      typeof action === "function"
        ? (action as (current: T) => T)(previous)
        : action;
    if (Object.is(previous, next)) return;
    value = next;
    try {
      const raw = JSON.stringify(next);
      if (raw === undefined) throw new TypeError("직렬화할 수 없는 저장 상태");
      port.write(raw);
      lastRaw = raw;
      memoryOnly = false;
    } catch {
      memoryOnly = true;
    }
    listeners.forEach((listener) => listener());
    port.publish();
  }
  return {
    getSnapshot,
    getServerSnapshot: () => initial,
    setValue,
    subscribe(listener: () => void) {
      listeners.add(listener);
      const unsubscribe = port.subscribe(listener);
      return () => {
        listeners.delete(listener);
        unsubscribe();
      };
    },
  };
}
