import { request, type FullConfig } from '@playwright/test';

// live UI 전체 실행 전에 자격을 한 번만 확인한다. 틀린 자격으로 91건을 돌리면 시험마다 로그인 실패가
// 쌓여 운영 관리자 로그인이 10분씩 잠긴다(5회 한도). 여기서 실패하면 실행 전체를 멈춘다(실패 기록 1회).
// 성공하면 만든 세션을 바로 로그아웃으로 회수한다. 자격 값은 메시지에 싣지 않는다.
export default async function livePreflight(config: FullConfig) {
  const baseURL = config.projects[0]?.use.baseURL ?? process.env.E2E_BASE_URL;
  if (!baseURL) throw new Error('E2E_BASE_URL이 없습니다');
  const origin = new URL(baseURL).origin;
  const api = await request.newContext({ baseURL, extraHTTPHeaders: { Origin: origin } });
  try {
    const login = await api.post('/api/auth/login', {
      data: { username: process.env.E2E_ADMIN_USERNAME, password: process.env.E2E_ADMIN_PASSWORD, next: '/' },
    });
    if (login.status() !== 200) {
      const reason = login.status() === 401 ? '자격 파일의 아이디·비밀번호가 운영과 다릅니다'
        : login.status() === 429 ? '운영 로그인이 잠겨 있습니다(10분 뒤 다시)'
          : login.status() === 403 ? 'E2E_BASE_URL origin을 운영이 같은 출처로 받지 않습니다'
            : '운영 로그인 응답이 예상과 다릅니다';
      throw new Error(`live 사전 로그인 실패(HTTP ${login.status()}): ${reason} — 시험을 시작하지 않습니다`);
    }
    const logout = await api.post('/api/auth/logout');
    if (!logout.ok()) throw new Error(`live 사전 로그인 세션을 회수하지 못했습니다(HTTP ${logout.status()})`);
  } finally {
    await api.dispose();
  }
}
