import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import type { Socket } from "node:net";
import { afterEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

afterEach(() => { vi.unstubAllEnvs(); vi.resetModules(); });

it("실제 HTTP 정지 요청을 중단하고 응답 스트림과 연결을 회수한 뒤 다음 감사를 저장한다", async () => {
  let mode: "stall" | "stream" | "ok" = "stall";
  let received = 0;
  const sockets = new Set<Socket>();
  const requestSockets: Socket[] = [];
  const server = createServer((request, response) => {
    received += 1;
    requestSockets.push(request.socket);
    request.resume();
    expect(request.url).toBe("/api/v1/admin/auth-events");
    if (mode === "stall") return;
    response.writeHead(200, { "Content-Type": "application/json" });
    if (mode === "stream") response.write("{");
    else response.end("{}");
  });
  server.on("connection", socket => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
  });
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as AddressInfo).port;
  vi.stubEnv("BACKEND_ORIGIN", `http://127.0.0.1:${port}`);
  vi.resetModules();
  const { recordAuthAuditEvent } = await import("./auth-audit");
  const request = new NextRequest("http://localhost/api/auth/login");
  try {
    const started = performance.now();
    await recordAuthAuditEvent(request, { eventType: "login", outcome: "denied" });
    expect(performance.now() - started).toBeGreaterThanOrEqual(1900);
    expect(performance.now() - started).toBeLessThan(3500);
    await vi.waitFor(() => expect(requestSockets[0].destroyed).toBe(true));
    mode = "stream";
    await recordAuthAuditEvent(request, { eventType: "login", outcome: "succeeded" });
    await vi.waitFor(() => expect(requestSockets[1].destroyed).toBe(true));
    mode = "ok";
    await recordAuthAuditEvent(request, { eventType: "logout", outcome: "succeeded" });
    expect(received).toBe(3);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
}, 10_000);
