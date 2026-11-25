// Docker builder 단계에서 `npm run build` 직전에 도는 진입점(frontend/Dockerfile). 판정은 vworld-build-key.mjs.
// 이 파일은 import되는 모듈이 아니라 늘 실행되는 진입점이다 — "직접 실행일 때만 main" 판별을 두지 않아
// 경로가 symlink로 달라져도 검사를 건너뛰지 않는다(fail closed).
import { checkVWorldBuildKey } from "./vworld-build-key.mjs";

const result = checkVWorldBuildKey(process.env);
const line = `[require-vworld-build-key] ${result.message}`;
if (result.level === "ok") console.log(line);
else console.error(line);
process.exitCode = result.ok ? 0 : 1;
