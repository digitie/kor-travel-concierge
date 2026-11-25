// frontend/scripts/require-vworld-build-key.mjs(판정: vworld-build-key.mjs) — UI 이미지 build에서 빈 VWorld 키를 실패로 바꾸는 검사.
// 2026-11-20~25 운영 UI 이미지가 build arg 없이 빌드돼 지도가 "키 없음"으로 떴다(T-211). Docker 없이 돈다.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, symlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(new URL('../../frontend/scripts/require-vworld-build-key.mjs', import.meta.url));
const dockerfile = readFileSync(new URL('../../frontend/Dockerfile', import.meta.url), 'utf8');
const compose = readFileSync(new URL('../../docker-compose.yml', import.meta.url), 'utf8');
const KEY = 'vw-fixture-Key-0123456789abcdef';
const { checkVWorldBuildKey } = await import(new URL('../../frontend/scripts/vworld-build-key.mjs', import.meta.url).href);

function run(env, entry = script) {
  // 부모 환경의 키·허용 값이 새어 들지 않게 PATH만 넘긴다.
  return spawnSync(process.execPath, [entry], { encoding: 'utf8', env: { PATH: process.env.PATH ?? '', ...env } });
}

test('symlink 경로로 실행해도 검사를 건너뛰지 않는다(fail closed)', () => {
  const link = join(mkdtempSync(join(tmpdir(), 'ktc-vworld-guard-')), 'guard.mjs');
  symlinkSync(script, link);
  assert.equal(run({}, link).status, 1);
});

test('키가 있으면 통과하고 값은 출력하지 않는다', () => {
  const r = run({ NEXT_PUBLIC_VWORLD_SERVICE_KEY: KEY });
  assert.equal(r.status, 0, r.stderr);
  assert.ok(!(r.stdout + r.stderr).includes(KEY));
});

test('키가 없거나 공백뿐이면 빌드를 실패시킨다', () => {
  for (const env of [{}, { NEXT_PUBLIC_VWORLD_SERVICE_KEY: '' }, { NEXT_PUBLIC_VWORLD_SERVICE_KEY: '  \t' }]) {
    const r = run(env);
    assert.equal(r.status, 1, JSON.stringify(env));
    assert.match(r.stderr, /NEXT_PUBLIC_VWORLD_SERVICE_KEY build arg가 비어 있습니다/);
    assert.match(r.stderr, /KTC_ALLOW_KEYLESS_MAP_BUILD=1/);
  }
});

test('번들을 고장 내는 값(앞뒤 공백·CR·따옴표·자리표시자)도 실패시키고 값은 출력하지 않는다', () => {
  for (const bad of [` ${KEY}`, `${KEY}\r`, `"${KEY}"`, `'${KEY}'`, `${KEY.slice(0, 8)} ${KEY.slice(8)}`]) {
    const r = run({ NEXT_PUBLIC_VWORLD_SERVICE_KEY: bad });
    assert.equal(r.status, 1, JSON.stringify(bad));
    assert.match(r.stderr, /공백·줄바꿈\(CR\)·따옴표가 섞여 있습니다/);
    assert.ok(!(r.stdout + r.stderr).includes(KEY.slice(8)));
  }
  for (const placeholder of ['your_vworld_browser_key_here', 'your_vworld_api_key_here']) {
    const r = run({ NEXT_PUBLIC_VWORLD_SERVICE_KEY: placeholder });
    assert.equal(r.status, 1, placeholder);
    assert.match(r.stderr, /자리표시자 그대로입니다/);
  }
  // .env.example의 자리표시자가 실제로 이 꼴인지(문서가 바뀌면 함께 본다).
  const example = readFileSync(new URL('../../.env.example', import.meta.url), 'utf8');
  const placeholder = example.match(/^NEXT_PUBLIC_VWORLD_SERVICE_KEY=(.*)$/m)?.[1];
  assert.equal(checkVWorldBuildKey({ NEXT_PUBLIC_VWORLD_SERVICE_KEY: placeholder }).ok, false);
});

test('명시 허용(=1)만 키 없는 빌드를 통과시키고 경고를 남긴다', () => {
  const r = run({ KTC_ALLOW_KEYLESS_MAP_BUILD: '1' });
  assert.equal(r.status, 0);
  assert.match(r.stderr, /경고: NEXT_PUBLIC_VWORLD_SERVICE_KEY 없이 빌드합니다/);
});

test('허용 값은 비우거나 1만 받는다 — 오타가 조용히 허용되지 않는다', () => {
  for (const allow of ['true', 'yes', '0', ' 1']) {
    const r = run({ KTC_ALLOW_KEYLESS_MAP_BUILD: allow, NEXT_PUBLIC_VWORLD_SERVICE_KEY: KEY });
    assert.equal(r.status, 1, allow);
    assert.match(r.stderr, /KTC_ALLOW_KEYLESS_MAP_BUILD는 비우거나 1이어야 합니다/);
    assert.ok(!r.stderr.includes(KEY));
  }
});

test('순수 함수 판정', () => {
  assert.equal(checkVWorldBuildKey({ NEXT_PUBLIC_VWORLD_SERVICE_KEY: KEY }).level, 'ok');
  assert.equal(checkVWorldBuildKey({}).level, 'error');
  assert.equal(checkVWorldBuildKey({ KTC_ALLOW_KEYLESS_MAP_BUILD: '1' }).level, 'warn');
  // 키가 있어도 허용 값이 이상하면 거부(설정 오타를 드러낸다).
  assert.equal(checkVWorldBuildKey({ KTC_ALLOW_KEYLESS_MAP_BUILD: 'on', NEXT_PUBLIC_VWORLD_SERVICE_KEY: KEY }).ok, false);
});

test('Dockerfile builder 단계가 next build 직전에 검사를 돌리고 허용 ARG를 받는다', () => {
  const builder = dockerfile.split(/^FROM /m).find((stage) => /^dependencies AS builder/.test(stage));
  assert.ok(builder, 'builder 단계가 없다');
  assert.match(builder, /^ARG NEXT_PUBLIC_VWORLD_SERVICE_KEY=""$/m);
  assert.match(builder, /^ARG KTC_ALLOW_KEYLESS_MAP_BUILD=""$/m);
  const runs = builder.split('\n').filter((line) => line.startsWith('RUN '));
  assert.deepEqual(runs, ['RUN node scripts/require-vworld-build-key.mjs && npm run build']);
  // 검사 대상 값이 ENV로 builder에 들어간다(COPY 전에 선언).
  assert.ok(builder.indexOf('NEXT_PUBLIC_VWORLD_SERVICE_KEY=${NEXT_PUBLIC_VWORLD_SERVICE_KEY}') < builder.indexOf('COPY . .'));
});

test('로컬 compose도 허용 ARG를 frontend build에 넘긴다', () => {
  assert.match(compose, /^\s+KTC_ALLOW_KEYLESS_MAP_BUILD: \$\{KTC_ALLOW_KEYLESS_MAP_BUILD:-\}$/m);
});
