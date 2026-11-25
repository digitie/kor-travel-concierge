// build 산출물(.next 등)에 브라우저 지도 키가 박히지 않았는지 본다(T-212). 키는 UI 서버가 실행 시 env에서
// 읽어 요청마다 내려줘야 한다 — 관리자 레이아웃이 정적 prerender로 돌아가거나 누가 키를 NEXT_PUBLIC 경로로
// 되돌리면 build 때의 값이 파일에 남는다.
//
// 사용: KTC_VWORLD_BROWSER_KEY=<build 때 준 값> node scripts/assert-no-baked-map-key.mjs <디렉터리>...
// 종료 코드 0 = 없음, 1 = 박힘(파일 경로만 출력), 2 = 사용 오류. 값·파일 내용은 출력하지 않는다.
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

const ENV = "KTC_VWORLD_BROWSER_KEY";
// 흔한 짧은 문자열과 우연히 겹쳐 오탐하지 않도록 검사 값은 길어야 한다.
const MIN_LENGTH = 16;
const log = (message) => console.error(`[assert-no-baked-map-key] ${message}`);

const needle = (process.env[ENV] ?? "").trim();
const roots = process.argv.slice(2);
if (needle.length < MIN_LENGTH) {
  log(`${ENV}에 검사할 값(${MIN_LENGTH}자 이상)을 두세요.`);
  process.exit(2);
}
if (roots.length === 0) {
  log("검사할 디렉터리를 지정하세요.");
  process.exit(2);
}
const missing = roots.filter((root) => !statSync(root, { throwIfNoEntry: false })?.isDirectory());
if (missing.length) {
  log(`디렉터리가 아닙니다: ${missing.join(", ")}`);
  process.exit(2);
}

const pattern = Buffer.from(needle, "utf8");
const hits = [];
let scanned = 0;
const walk = (target) => {
  const stat = statSync(target, { throwIfNoEntry: false });
  if (stat?.isDirectory()) {
    for (const entry of readdirSync(target)) walk(path.join(target, entry));
  } else if (stat?.isFile()) {
    scanned += 1;
    if (readFileSync(target).includes(pattern)) hits.push(target);
  }
};
for (const root of roots) walk(root);

if (hits.length) {
  log(`지도 키가 build 산출물 ${hits.length}개 파일에 박혔습니다(파일 ${scanned}개 검사):\n${hits.map((hit) => `  ${hit}`).join("\n")}`);
  process.exit(1);
}
if (scanned === 0) {
  // 빈 디렉터리 통과는 검사를 안 한 것과 같다 — build가 실패했거나 경로가 틀렸다.
  log(`검사할 파일이 없습니다: ${roots.join(", ")}`);
  process.exit(2);
}
console.log(`[assert-no-baked-map-key] 지도 키 없음 — 파일 ${scanned}개 검사(${roots.join(", ")}).`);
