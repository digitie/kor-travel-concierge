import type { DestinationGroupDim } from "./api";

export const SOURCE_GROUP_OPTIONS = [
  { value: "none", label: "전체" },
  { value: "channel", label: "유튜버별" },
  { value: "playlist", label: "재생목록별" },
  { value: "keyword", label: "검색어별" },
] as const satisfies readonly { value: DestinationGroupDim; label: string }[];

export function sourceGroupLabel(value: DestinationGroupDim) {
  return (
    SOURCE_GROUP_OPTIONS.find((option) => option.value === value)?.label ??
    "전체"
  );
}
