import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { isPublicPath } from "@/lib/public-paths";

/**
 * maplibre worker 배선이 실제로 성립하는지 센다(2026-11-23 prod 이미지 0956fa6b 격리 점검:
 * `/`·`/review`에서 "Worker failed to load"). 이름을 손으로 맞추지 않고 복사 스크립트·소스 URL·
 * 빌드 훅·인증 예외·런타임 이미지가 서로 맞는지 본다. 하나만 바뀌어도 빨개진다.
 */
const FRONTEND = path.resolve(__dirname, "..", "..");
const SCRIPT = path.join(FRONTEND, "scripts", "copy-maplibre-worker.mjs");
const MAP_VIEW = path.join(FRONTEND, "src", "components", "VWorldMap.tsx");

function copiedFileNames(): string[] {
  const match = readFileSync(SCRIPT, "utf8").match(/WORKER_FILES\s*=\s*\[([^\]]+)\]/);
  if (match === null) throw new Error("복사 스크립트에서 WORKER_FILES를 찾지 못했다");
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

function configuredWorkerUrl(): string {
  const source = readFileSync(MAP_VIEW, "utf8");
  const constant = source.match(/MAPLIBRE_WORKER_URL\s*=\s*"([^"]+)"/);
  if (constant === null) throw new Error("VWorldMap.tsx에 worker URL 상수가 없다");
  expect(source).toMatch(/setWorkerUrl\(MAPLIBRE_WORKER_URL\)/);
  return constant[1];
}

describe("maplibre worker 배선", () => {
  it("worker와 형제 파일을 함께 옮기고 소스가 그 파일을 가리킨다", () => {
    const files = copiedFileNames();
    expect(files).toEqual(expect.arrayContaining(["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]));
    const url = configuredWorkerUrl();
    expect(url.startsWith("/maplibre/")).toBe(true);
    expect(files).toContain(path.posix.basename(url));
  });

  it("빌드·개발 훅이 스크립트를 부르고 런타임 이미지가 public을 싣는다", () => {
    const pkg = JSON.parse(readFileSync(path.join(FRONTEND, "package.json"), "utf8")) as {
      scripts: Record<string, string>;
    };
    for (const hook of ["prebuild", "predev", "predev:live"]) {
      expect(pkg.scripts[hook] ?? "").toContain("copy-maplibre-worker.mjs");
    }
    const dockerfile = readFileSync(path.join(FRONTEND, "Dockerfile"), "utf8");
    // build 모드 컨테이너는 node 사용자로 prebuild를 다시 돌리므로 node 소유여야 한다.
    expect(dockerfile).toMatch(/COPY --from=builder --chown=node:node \/app\/public \.\/public/);
  });

  it("worker 경로는 세션 없이도 열린다(만료 뒤 로그인 HTML로 redirect되지 않는다)", () => {
    expect(isPublicPath(configuredWorkerUrl())).toBe(true);
    expect(isPublicPath("/review")).toBe(false);
  });

  it("스크립트를 실제로 돌리면 두 파일이 모두 생긴다", () => {
    const workdir = mkdtempSync(path.join(tmpdir(), "maplibre-worker-"));
    execFileSync(process.execPath, [SCRIPT], { cwd: workdir, stdio: "pipe" });
    for (const file of copiedFileNames()) {
      expect(existsSync(path.join(workdir, "public", "maplibre", file))).toBe(true);
    }
    const worker = readFileSync(path.join(workdir, "public", "maplibre", "maplibre-gl-worker.mjs"), "utf8");
    expect(worker.length).toBeGreaterThan(1000);
  });
});
