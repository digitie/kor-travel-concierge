import { describe, expect, it } from "vitest";
import {
  createPersistedStateStore,
  type StorageStatePort,
} from "./persisted-state-store";

function storage(raw: string | null) {
  const listeners = new Set<() => void>();
  const writes: string[] = [];
  const port: StorageStatePort = {
    read: () => raw,
    write: (value) => {
      raw = value;
      writes.push(value);
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    publish: () => listeners.forEach((listener) => listener()),
  };
  return { port, writes };
}
describe("저장소 상태 구독", () => {
  it("SSR 초기값을 저장하지 않고 기존 값을 복원하며 snapshot 객체를 캐시한다", () => {
    const data = storage("[1,2]");
    const store = createPersistedStateStore<number[]>([], data.port);
    expect(store.getServerSnapshot()).toEqual([]);
    expect(store.getSnapshot()).toEqual([1, 2]);
    expect(store.getSnapshot()).toBe(store.getSnapshot());
    expect(data.writes).toEqual([]);
  });
  it("같은 key의 소비자가 갱신을 구독하고 함수형 갱신도 최신 저장값을 사용한다", () => {
    const data = storage("1");
    const first = createPersistedStateStore(0, data.port);
    const second = createPersistedStateStore(0, data.port);
    const snapshots: number[] = [];
    const unsubscribe = second.subscribe(() =>
      snapshots.push(second.getSnapshot()),
    );
    first.setValue((value) => value + 1);
    second.setValue((value) => value + 1);
    expect(first.getSnapshot()).toBe(3);
    expect(snapshots).toContain(2);
    unsubscribe();
    first.setValue(4);
    expect(snapshots.at(-1)).toBe(3);
  });
  it("손상·차단·quota 실패에서도 화면 입력을 이전 저장값으로 되돌리지 않는다", () => {
    const data = storage("broken");
    const store = createPersistedStateStore("initial", {
      ...data.port,
      write: () => {
        throw new Error("quota");
      },
    });
    expect(store.getSnapshot()).toBe("initial");
    store.setValue("edited");
    expect(store.getSnapshot()).toBe("edited");
    store.setValue((value) => value + "!");
    expect(store.getSnapshot()).toBe("edited!");
  });
});
