import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
const auth = vi.hoisted(() => ({ requestSessionStatus: vi.fn(async () => "unavailable"), adminUsernameFromEnv: () => "unit-user", sanitizeLocalPath: (value: string | null) => value ?? "/" }));
vi.mock("@/lib/auth", () => auth);
import { proxy } from "@/proxy";
import { POST as bff } from "@/app/api/v1/[...path]/route";
beforeEach(() => { vi.clearAllMocks(); vi.stubGlobal("fetch", vi.fn()); });
afterEach(() => vi.unstubAllGlobals());
it.each(["/settings", "/api/v1/settings"])("상태 I/O 장애의 %s는 세션 폐기 redirect 없이 503으로 재시도한다", async (path) => {
  auth.requestSessionStatus.mockResolvedValue("unavailable");
  const response = await proxy(new NextRequest(`http://localhost${path}`));
  expect(response?.status).toBe(503); expect(response?.headers.get("location")).toBeNull();
  expect(response?.headers.get("set-cookie")).toBeNull(); expect(response?.headers.get("retry-after")).toBe("1");
});
it("BFF 상태 장애는 body·upstream·key 주입 전에 503으로 거절한다", async () => {
  auth.requestSessionStatus.mockResolvedValue("unavailable");
  const request = new NextRequest("http://localhost/api/v1/settings", { method: "POST", body: "{}" });
  const body = vi.spyOn(request, "arrayBuffer");
  const response = await bff(request, { params: Promise.resolve({ path: ["settings"] }) });
  expect(response.status).toBe(503); expect(body).not.toHaveBeenCalled(); expect(fetch).not.toHaveBeenCalled();
  expect(response.headers.get("set-cookie")).toBeNull();
});
it("잘못된 세션의 BFF는 계속 401로 거절한다", async () => {
  auth.requestSessionStatus.mockResolvedValue("invalid");
  const response = await bff(new NextRequest("http://localhost/api/v1/settings"), { params: Promise.resolve({ path: ["settings"] }) });
  expect(response.status).toBe(401); expect(fetch).not.toHaveBeenCalled();
});
