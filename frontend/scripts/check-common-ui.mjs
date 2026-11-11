// 공통 구현 우회가 다시 유입되면 CI에서 실패한다.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
const roots = ["src"];
function files(dir) { return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(join(dir, entry.name)) : /\.tsx?$/.test(entry.name) && !/\.test\./.test(entry.name) ? [join(dir, entry.name)] : []); }
const sources = roots.flatMap(files).map(path => [path, readFileSync(path, "utf8")]);
const errors = [];
for (const [path, source] of sources) {
  if (/from\s*["\x27](?:@base-ui\/|@floating-ui\/)/.test(source)) errors.push(path + ": Base UI 직접 구현 금지");
  if (/<table(?:\s|>)/.test(source)) errors.push(path + ": 공통 VirtualTable 사용 필요");
  if (/from\s*["\x27]@tanstack\/react-(?:table|virtual)/.test(source)) errors.push(path + ": 공통 table 계약 사용 필요");
}
const combined = sources.map(([, source]) => source).join("\n");
for (const pattern of [/useForm/, /zustand/, /@kor-travel\/ui(?:\/login-form)?["\x27]/, /@kor-travel\/ui\/virtual-table/]) {
  if (!pattern.test(combined)) errors.push("필수 공통 소비 또는 폼/상태 사용 누락: " + pattern);
}
const fontSource = readFileSync("src/app/layout.tsx", "utf8");
if (!fontSource.includes("@kor-travel/tokens/font.css")) errors.push("공통 Pretendard CSS 사용 필요");
if (errors.length) { console.error(errors.join("\n")); process.exitCode = 1; } else console.log("공통 UI 소비 경계 일치");
