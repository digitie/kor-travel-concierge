// scripts/n150-live-ui-e2e.sh의 자격 파일 검사·값 비노출·인자 제한 계약.
// sudo·stat·docker·gate는 가짜로 바꿔 root 없이 돈다(실제 브라우저·운영 접속 없음).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, symlinkSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const script = fileURLToPath(new URL('../../scripts/n150-live-ui-e2e.sh', import.meta.url));
const PASSWORD = 'pw-Zq8!value with space';

function sandbox() {
  const root = mkdtempSync(join(tmpdir(), 'ktc-live-e2e-'));
  const bin = join(root, 'bin');
  mkdirSync(bin);
  const exe = (name, body) => {
    writeFileSync(join(bin, name), `#!/bin/bash\n${body}\n`);
    chmodSync(join(bin, name), 0o755);
  };
  // sudo: 권한 상승 없이 인자만 실행한다(가짜 stat이 PATH 앞에 남는다).
  exe('sudo', 'while [[ "$1" == -n || "$1" == -- ]]; do shift; done\n[[ "$1" == true ]] && exit 0\nexec "$@"');
  exe('stat', 'if [[ -d "${@: -1}" ]]; then echo "${FAKE_DIR_META:-0 700}"; else echo "${FAKE_FILE_META:-0 600}"; fi');
  exe('docker', 'printf "%s\\n" "$@" > "$FAKE_DOCKER_ARGS"\nprintf "%s\\n" "E2E_BASE_URL=$E2E_BASE_URL" "E2E_ADMIN_USERNAME=$E2E_ADMIN_USERNAME" "E2E_ADMIN_PASSWORD=$E2E_ADMIN_PASSWORD" "KTC_LIVE_E2E_WRITE=${KTC_LIVE_E2E_WRITE:-}" > "$FAKE_DOCKER_ENV"');
  exe('gate', 'exec "$@"');
  const credDir = join(root, 'secret');
  mkdirSync(credDir);
  const cred = join(credDir, 'concierge-e2e.env');
  return { root, bin, cred, args: join(root, 'docker-args'), env: join(root, 'docker-env') };
}

function run(box, { args = [], env = {}, bashFlags = [] } = {}) {
  const result = spawnSync('bash', [...bashFlags, script, ...args], {
    encoding: 'utf8',
    env: {
      PATH: `${box.bin}:/usr/bin:/bin`, HOME: box.root,
      KTC_LIVE_E2E_CREDENTIALS: box.cred, KTC_LIVE_E2E_GATE: join(box.bin, 'gate'),
      KTC_LIVE_E2E_DOCKER: join(box.bin, 'docker'),
      FAKE_DOCKER_ARGS: box.args, FAKE_DOCKER_ENV: box.env, ...env,
    },
  });
  const output = result.stdout + result.stderr;
  assert.ok(!output.includes(PASSWORD), '자격 값이 출력에 나왔습니다');
  return { ...result, output };
}

const validFile = `# e2e 전용\nE2E_ADMIN_USERNAME=admin\nE2E_ADMIN_PASSWORD="${PASSWORD}"\n`;

test('xtrace(bash -x) 실행은 자격 파일을 읽기 전에 거부한다', () => {
  const box = sandbox();
  writeFileSync(box.cred, validFile);
  const result = run(box, { bashFlags: ['-x'] });
  assert.equal(result.status, 2);
  assert.match(result.output, /xtrace/);
  assert.equal(existsSync(box.args), false);
});

test('설정·reporter를 바꾸는 인자는 거부한다', () => {
  const box = sandbox();
  writeFileSync(box.cred, validFile);
  for (const arg of ['--config', '-c', '--reporter=line', '--workers=4', 'live-forms-actions.spec.ts']) {
    const result = run(box, { args: [arg, 'x'] });
    assert.equal(result.status, 2, arg);
    assert.match(result.output, /허용하지 않는 인자/);
  }
  assert.equal(existsSync(box.args), false);
});

test('root 소유 0600이 아닌 자격 파일·디렉터리·심볼릭 링크는 거부한다', () => {
  const box = sandbox();
  writeFileSync(box.cred, validFile);
  for (const [env, pattern] of [
    [{ FAKE_FILE_META: '0 644' }, /root 소유·0600/],
    [{ FAKE_FILE_META: '1000 600' }, /root 소유·0600/],
    [{ FAKE_DIR_META: '1000 700' }, /디렉터리는 root 소유/],
    [{ FAKE_DIR_META: '0 777' }, /group·other 쓰기/],
  ]) {
    const result = run(box, { env });
    assert.equal(result.status, 4, JSON.stringify(env));
    assert.match(result.output, pattern);
  }
  const link = join(box.root, 'secret', 'link.env');
  symlinkSync(box.cred, link);
  const linked = run(box, { env: { KTC_LIVE_E2E_CREDENTIALS: link } });
  assert.equal(linked.status, 3);
  assert.match(linked.output, /일반 파일이 아닙니다/);
  const missing = run(box, { env: { KTC_LIVE_E2E_CREDENTIALS: join(box.root, 'secret', 'none.env') } });
  assert.equal(missing.status, 3);
  assert.equal(existsSync(box.args), false);
});

test('허용하지 않는 키·형식 오류·중복 키는 값 없이 행 번호만 알린다', () => {
  const box = sandbox();
  for (const [content, pattern] of [
    [`${validFile}KTC_ADMIN_PASSWORD_HASH=${PASSWORD}\n`, /4행의 키 KTC_ADMIN_PASSWORD_HASH는 허용하지 않습니다/],
    [`${validFile}${PASSWORD}\n`, /4행이 KEY=VALUE 형식이 아닙니다/],
    [`${validFile}E2E_ADMIN_PASSWORD=${PASSWORD}\n`, /E2E_ADMIN_PASSWORD가 두 번/],
    ['E2E_ADMIN_USERNAME=admin\n', /E2E_ADMIN_PASSWORD가 없습니다/],
    [`${validFile}E2E_BASE_URL=https://example.test/login\n`, /경로 없이/],
    [`${validFile}E2E_BASE_URL=http://concierge.example.test\n`, /loopback이 아니면 https/],
  ]) {
    writeFileSync(box.cred, content);
    const result = run(box);
    assert.equal(result.status, 2, content);
    assert.match(result.output, pattern);
  }
  assert.equal(existsSync(box.args), false);
});

test('정상 자격은 이름만 docker argv에 싣고 값은 환경변수로 넘기며, 읽기 전용 설정만 돈다', () => {
  const box = sandbox();
  writeFileSync(box.cred, `${validFile}export E2E_BASE_URL='https://concierge.example.test/'\n`);
  const result = run(box, { args: ['--grep', '로그인'] });
  assert.equal(result.status, 0, result.output);
  const argv = readFileSync(box.args, 'utf8');
  assert.ok(!argv.includes(PASSWORD));
  assert.match(argv, /^--env\nE2E_ADMIN_PASSWORD$/m);
  assert.match(argv, /^LIVE_E2E_CONFIG=playwright\.live-ui\.config\.ts$/m);
  assert.match(argv, /^LIVE_E2E_REDACT=E2E_ADMIN_PASSWORD$/m);
  assert.match(argv, /^mcr\.microsoft\.com\/playwright:v[0-9.]+-noble$/m);
  assert.match(argv, /^--grep\n로그인$/m);
  assert.doesNotMatch(argv, /KTC_LIVE_E2E_WRITE/);
  assert.match(argv, /^PLAYWRIGHT_NO_COPY_PROMPT=1$/m);
  assert.match(argv, /^LIVE_E2E_SECRET_VARS=E2E_ADMIN_PASSWORD,E2E_ADMIN_USERNAME$/m);
  assert.match(argv, /^--shm-size=1g$/m);
  assert.doesNotMatch(argv, /--ipc=host/);
  // 컨테이너에는 tests/만 싣는다.
  assert.match(argv, /\/tests:\/work$/m);
  const env = readFileSync(box.env, 'utf8');
  assert.match(env, /^E2E_BASE_URL=https:\/\/concierge\.example\.test$/m);
  assert.match(env, /^E2E_ADMIN_USERNAME=admin$/m);
  assert.ok(env.includes(`E2E_ADMIN_PASSWORD=${PASSWORD}\n`));
  assert.match(env, /^KTC_LIVE_E2E_WRITE=$/m);
  assert.match(result.output, /값은 출력하지 않습니다/);
});

test('대상 URL 기본값은 loopback UI이고, 쓰기 스펙은 KTC_LIVE_E2E_WRITE=1일 때만 넘긴다', () => {
  const box = sandbox();
  writeFileSync(box.cred, validFile);
  const result = run(box, { env: { KTC_LIVE_E2E_WRITE: '1' } });
  assert.equal(result.status, 0, result.output);
  assert.match(readFileSync(box.args, 'utf8'), /^--env\nKTC_LIVE_E2E_WRITE$/m);
  const env = readFileSync(box.env, 'utf8');
  assert.match(env, /^E2E_BASE_URL=http:\/\/127\.0\.0\.1:12605$/m);
  assert.match(env, /^KTC_LIVE_E2E_WRITE=1$/m);
  assert.equal(run(box, { env: { KTC_LIVE_E2E_WRITE: 'yes' } }).status, 2);
});

test('test gate가 없으면 실행하지 않는다', () => {
  const box = sandbox();
  writeFileSync(box.cred, validFile);
  const result = run(box, { env: { KTC_LIVE_E2E_GATE: join(box.root, 'missing-gate.sh') } });
  assert.equal(result.status, 2);
  assert.match(result.output, /test gate/);
  assert.equal(existsSync(box.args), false);
});

test('경로 중간의 심볼릭 링크와 없는 docker 실행 파일은 거부한다', () => {
  const box = sandbox();
  writeFileSync(box.cred, validFile);
  const linkedDir = join(box.root, 'linked');
  symlinkSync(join(box.root, 'secret'), linkedDir);
  const viaLink = run(box, { env: { KTC_LIVE_E2E_CREDENTIALS: join(linkedDir, 'concierge-e2e.env') } });
  assert.equal(viaLink.status, 3);
  assert.match(viaLink.output, /심볼릭 링크/);
  const noDocker = run(box, { env: { KTC_LIVE_E2E_DOCKER: join(box.root, 'no-docker') } });
  assert.equal(noDocker.status, 2);
  assert.match(noDocker.output, /docker 실행 파일이 없습니다/);
  assert.equal(existsSync(box.args), false);
});

test('live 설정의 모든 시험 파일은 운영 write 차단을 건다', () => {
  const testsDir = fileURLToPath(new URL('..', import.meta.url));
  const config = readFileSync(join(testsDir, 'playwright.live-ui.config.ts'), 'utf8');
  assert.match(config, /globalSetup: '\.\/e2e\/live-login-preflight\.ts'/);
  assert.match(config, /trace: 'off'/);
  const files = [...config.matchAll(/'([\w-]+\.spec\.ts)'/g)].map(match => match[1]);
  assert.equal(files.length, 5);
  for (const file of files) {
    const source = readFileSync(join(testsDir, 'e2e', file), 'utf8');
    assert.ok(source.includes("from './live-ui-fixtures'") || source.includes('live-write-guard'), file);
  }
  assert.ok(readFileSync(join(testsDir, 'playwright.config.ts'), 'utf8').includes("testIgnore: ['**/*.write.live.spec.ts']"));
});
