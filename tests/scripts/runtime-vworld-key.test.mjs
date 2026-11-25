// 브라우저 지도 키 실행 시 주입(T-212)의 정적 계약과 build 산출물 검사 스크립트. Docker·브라우저 없이 돈다.
// 실제 주입(실행 env → 지도 타일 요청, JS chunk 미포함)은 tests/e2e/common-ui.spec.ts가 next start로 본다.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = (relative) => fileURLToPath(new URL(`../../${relative}`, import.meta.url));
const read = (relative) => readFileSync(root(relative), 'utf8');
const script = root('frontend/scripts/assert-no-baked-map-key.mjs');
const NEEDLE = 'ktc-test-sentinel-0123456789abcdef';

function scan(dirs, needle = NEEDLE) {
  // 부모 환경의 실제 키가 새어 들지 않게 PATH와 검사 값만 넘긴다.
  return spawnSync(process.execPath, [script, ...dirs], {
    encoding: 'utf8',
    env: { PATH: process.env.PATH ?? '', KTC_VWORLD_BROWSER_KEY: needle },
  });
}

function fixture(files) {
  const dir = mkdtempSync(join(tmpdir(), 'ktc-baked-key-'));
  for (const [name, body] of Object.entries(files)) {
    mkdirSync(join(dir, name, '..'), { recursive: true });
    writeFileSync(join(dir, name), body);
  }
  return dir;
}

test('산출물에 키가 있으면 실패하고 파일 경로만 출력한다(값은 출력하지 않는다)', () => {
  const dir = fixture({ 'static/chunks/a.js': `x="${NEEDLE}"`, 'server/app/page.html': '<p>ok</p>' });
  const r = scan([dir]);
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /1개 파일에 박혔습니다/);
  assert.match(r.stderr, /a\.js/);
  assert.ok(!`${r.stdout}${r.stderr}`.includes(NEEDLE), '검사 값이 출력에 새면 안 된다');
});

test('키가 없으면 통과한다', () => {
  const r = scan([fixture({ 'static/chunks/a.js': 'x=""', 'BUILD_ID': 'abc' })]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /파일 2개 검사/);
});

test('짧은 검사 값·빈 디렉터리·없는 경로는 사용 오류(2)로 닫힌다', () => {
  assert.equal(scan([fixture({ a: 'x' })], 'short').status, 2);
  assert.equal(scan([mkdtempSync(join(tmpdir(), 'ktc-baked-empty-'))]).status, 2);
  assert.equal(scan([join(tmpdir(), 'ktc-baked-key-missing-dir')]).status, 2);
  assert.equal(scan([]).status, 2);
});

test('frontend 소스는 지도 키를 NEXT_PUBLIC 경로로 읽지 않는다', () => {
  const offenders = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      const target = join(dir, entry);
      if (statSync(target).isDirectory()) walk(target);
      // env 접근(`process.env.NEXT_PUBLIC_VWORLD…`, `env["NEXT_PUBLIC_VWORLD…"]`)만 찾는다 — 경고 문구의 옛 이름 안내는
      // 읽기가 아니다. 단위 시험(*.test.ts)은 옛 이름을 "읽지 않음"의 음성 입력으로 쓴다.
      else if (/\.(tsx?|mjs|js)$/.test(entry) && !/\.test\.tsx?$/.test(entry)
        && /\benv\s*(?:\.\s*|\[\s*["'`])NEXT_PUBLIC_VWORLD/.test(readFileSync(target, 'utf8'))) offenders.push(target);
    }
  };
  walk(root('frontend/src'));
  assert.deepEqual(offenders, []);
  assert.match(read('frontend/src/lib/vworld-browser-key.ts'), /VWORLD_BROWSER_KEY_ENV = "KTC_VWORLD_BROWSER_KEY"/);
});

test('관리자 레이아웃은 요청 시점 렌더링으로 키를 읽는다(정적 prerender면 build env가 박힌다)', () => {
  const layout = read('frontend/src/app/(admin)/layout.tsx');
  assert.match(layout, /^import \{ connection \} from "next\/server";$/m);
  const body = layout.slice(layout.indexOf('export default async function AdminLayout'));
  assert.ok(body.indexOf('await connection();') >= 0, 'connection() 호출이 없다');
  assert.ok(body.indexOf('await connection();') < body.indexOf('readVWorldBrowserKey()'), 'env는 connection() 뒤에 읽어야 한다');
});

test('proxy 인증 예외는 경로 prefix로만 정한다(확장자로 끝나는 관리자 경로가 인증을 건너뛰지 않게)', () => {
  const proxy = read('frontend/src/proxy.ts');
  const matcher = proxy.slice(proxy.indexOf('export const config'));
  assert.match(matcher, /matcher: \["\/\(\(\?!_next\/static\/\|_next\/image\|favicon\\\\\.ico\$\|maplibre\/\)\.\*\)"\]/);
  assert.doesNotMatch(matcher, /png|css|\bjs\b/);
});

test('Dockerfile·compose build에는 지도 키 입력이 없고 compose 실행 env로 넘긴다', () => {
  // 주석(설명)은 빼고 실제 지시만 본다.
  const dockerfile = read('frontend/Dockerfile').split('\n').filter((line) => !line.trimStart().startsWith('#')).join('\n');
  assert.doesNotMatch(dockerfile, /VWORLD|KTC_ALLOW_KEYLESS_MAP_BUILD|require-vworld-build-key/);
  assert.match(dockerfile, /^RUN npm run build$/m);
  const compose = read('docker-compose.yml');
  const frontend = compose.slice(compose.indexOf('\n  frontend:\n'));
  const build = frontend.slice(0, frontend.indexOf('\n    env_file:'));
  assert.doesNotMatch(build, /VWORLD|KTC_ALLOW_KEYLESS_MAP_BUILD/);
  assert.match(frontend, /^ {6}KTC_VWORLD_BROWSER_KEY: \$\{KTC_VWORLD_BROWSER_KEY:-\}$/m);
  assert.doesNotMatch(compose, /NEXT_PUBLIC_VWORLD_SERVICE_KEY|KTC_ALLOW_KEYLESS_MAP_BUILD/);
});

test('.env.example은 실행 시 키 이름만 안내한다', () => {
  const example = read('.env.example');
  assert.match(example, /^KTC_VWORLD_BROWSER_KEY=your_vworld_browser_key_here$/m);
  assert.doesNotMatch(example, /^(NEXT_PUBLIC_VWORLD_SERVICE_KEY|KTC_ALLOW_KEYLESS_MAP_BUILD)=/m);
});
