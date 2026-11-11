import { describe, expect, it } from "vitest";
import { keyedItems } from "./keyed-items";

describe("ID가 없는 값 목록의 React key", () => {
  it("서로 다른 값의 삽입·재정렬이 기존 key를 바꾸지 않는다", () => {
    const before = keyedItems(["a", "b"], value => value);
    const after = keyedItems(["new", "b", "a"], value => value);
    expect(after[1].key).toBe(before[1].key);
    expect(after[2].key).toBe(before[0].key);
  });
  it("동일 내용의 여러 항목도 key가 충돌하지 않는다", () => {
    const entries = keyedItems(["same", "same", "other", "same"], value => value);
    expect(new Set(entries.map(entry => entry.key)).size).toBe(entries.length);
  });
});
