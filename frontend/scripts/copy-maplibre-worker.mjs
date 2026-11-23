/**
 * maplibre-gl worker를 `public/maplibre/`로 복사한다(`predev`·`prebuild`).
 *
 * 왜 필요한가: maplibre-gl 6은 기본 worker URL을 `import.meta.url` 기준으로 계산한다.
 * `next build --webpack`은 번들 안의 `import.meta.url`을 빌드 때의 `file://` 경로로
 * 바꾸므로 maplibre가 http(s)가 아닌 URL을 보고 빈 worker URL을 만든다. 그러면
 * `new Worker("")`가 현재 문서(HTML)를 스크립트로 읽어 "Worker failed to load"가 나고
 * GeoJSON·vector source 처리가 모두 멈춘다(2026-11-23 prod 이미지 0956fa6b 격리 점검,
 * `/`·`/review`). Map admin과 같은 처방이다 — worker와 형제 파일을 같은 디렉터리에
 * 복사해 정적으로 서빙하고 `setWorkerUrl`로 그 경로를 가리킨다.
 */

import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

// worker가 형제 파일을 상대 import하는 버전이 있으므로 둘을 함께 옮긴다.
export const WORKER_FILES = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

const require = createRequire(import.meta.url);
const dist = path.join(path.dirname(require.resolve("maplibre-gl/package.json")), "dist");
const dest = path.join(process.cwd(), "public", "maplibre");

mkdirSync(dest, { recursive: true });
for (const file of WORKER_FILES) {
  copyFileSync(path.join(dist, file), path.join(dest, file));
}

console.log(`maplibre worker 복사: ${WORKER_FILES.join(", ")} -> ${dest}`);
