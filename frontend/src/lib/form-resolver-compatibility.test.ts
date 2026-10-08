import { expect, it } from "vitest";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";

// Zod 4 오류가 거절된 Promise로 새어 나가면 RHF는 필드 오류를 표시하지 못한다.
it("설치한 resolver는 Zod 4 issues를 필드 오류로 반환한다", async () => {
  const resolver = zodResolver(z.object({ targetValue: z.string().min(1, "수집 대상을 입력하세요.") }));
  const result = await resolver({ targetValue: "" }, undefined, {
    fields: {}, shouldUseNativeValidation: false, criteriaMode: "firstError",
  });
  expect(result.errors.targetValue?.message).toBe("수집 대상을 입력하세요.");
  expect(result.values).toEqual({});
});
