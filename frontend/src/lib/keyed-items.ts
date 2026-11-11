/** ID가 없는 읽기 전용 값 목록의 중복 항목도 안정적으로 식별한다. */
export function keyedItems<T>(items: readonly T[], identity: (item: T) => string) {
  const occurrences = new Map<string, number>();
  return items.map((item) => {
    const base = identity(item);
    const occurrence = occurrences.get(base) ?? 0;
    occurrences.set(base, occurrence + 1);
    return { item, key: JSON.stringify([base, occurrence]) };
  });
}
