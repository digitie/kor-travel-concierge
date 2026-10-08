import { test, expect, login, choose, fault, allowed, noOverflow } from './live-ui-fixtures';
import type { Page } from '@playwright/test';
const list = (page: Page) => page.getByRole('region', { name: '장소 목록', exact: true });
const rows = (page: Page) => list(page).locator('div[data-selected]');
async function results(page: Page) {
  const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/destinations');
  await login(page, '/'); const body = await (await response).json();
  expect(body.items.length).toBeGreaterThan(1); await expect(rows(page)).toHaveCount(body.items.length); return body;
}
for (const key of ['click', 'Enter', 'Space']) {
  test(`실제 장소 목록 선택과 마커 identity를 확인한다 ${key}`, async ({ page }) => {
    const body = await results(page); const row = rows(page).first(); const select = row.locator('button').first();
    if (key === 'click') await select.click(); else { await select.focus(); await page.keyboard.press(key); }
    await expect(row).toHaveAttribute('data-selected', 'true');
    await expect(row).toContainText(body.items[0].name);
    const marker = page.locator(`[data-interaction-id="1"]`);
    await expect(marker).toHaveAttribute('data-selected', 'true');
  });
}
test('실제 장소 검색·정렬 요청과 내보내기 선택이 독립적으로 유지된다', async ({ page }) => {
  const body = await results(page); const row = rows(page).first();
  await row.locator('button').first().click(); await expect(row).toHaveAttribute('data-selected', 'true');
  await row.getByRole('checkbox').check(); await expect(list(page).getByRole('button', { name: '선택 1 내보내기', exact: true })).toBeVisible();
  for (const option of ['GPX','KML','XLSX']) { await choose(page, '내보내기 형식', option); await expect(page.getByLabel('내보내기 형식')).toContainText(option); }
  const response = page.waitForResponse(r => { const u = new URL(r.url()); return u.pathname === '/api/v1/destinations' && u.searchParams.get('q') === body.items[0].name; });
  await page.getByLabel('장소 글자 검색').fill(body.items[0].name); expect((await response).status()).toBe(200);
  await expect(rows(page).filter({ hasText: body.items[0].name }).first()).toBeVisible();
  await expect(list(page).getByRole('button', { name: '선택 1 내보내기', exact: true })).toBeVisible();
  const sorted = page.waitForResponse(r => { const u = new URL(r.url()); return u.pathname === '/api/v1/destinations' && u.searchParams.get('sort') === 'name'; });
  await choose(page, '장소 정렬', '이름 순'); const sortedResponse = await sorted; expect(sortedResponse.status()).toBe(200);
  const sortedBody = await sortedResponse.json(); expect(sortedBody.items.length).toBeGreaterThan(0);
  // 필터 identity 변경 시 기본 첫 장소가 선택된다. 내보내기 cart는 별도 상태다.
  await expect(rows(page).first()).toContainText(sortedBody.items[0].name);
  await expect(rows(page).first()).toHaveAttribute('data-selected', 'true');
  await expect(list(page).getByRole('button', { name: '선택 1 내보내기', exact: true })).toBeVisible();
});
for (const mobile of [false,true]) {
  test(`장소 상세는 같은 identity를 표시하고 목록으로 돌아온다 ${mobile ? 'mobile' : 'desktop'}`, async ({ page }, info) => {
    await page.setViewportSize({ width: mobile ? 390 : 1440, height: 1000 });
    const body = await results(page); const item = body.items[0];
    const response = page.waitForResponse(r => new URL(r.url()).pathname === `/api/v1/destinations/${item.place_id}/detail`);
    await rows(page).first().getByRole('button', { name: `${item.name} 상세`, exact: true }).click();
    expect((await response).status()).toBe(200);
    if (mobile) {
      await expect(page).toHaveURL(new RegExp(`/place/${item.place_id}$`)); await expect(page.locator('#main-content')).toContainText(item.name);
      await page.getByRole('link', { name: '결과로', exact: true }).click(); await expect(list(page)).toBeVisible();
    } else {
      await expect(page.getByRole('dialog', { name: '장소 상세' })).toContainText(item.name);
      await page.screenshot({ path: info.outputPath('place-detail.png') });
      await page.keyboard.press('Escape'); await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(rows(page).first().getByRole('button', { name: `${item.name} 상세`, exact: true })).toBeFocused();
    }
    await noOverflow(page);
  });
}
for (const warm of [false,true]) {
  test(`장소 목록 장애는 빈 성공과 구분하고 재조회로 복구한다 ${warm ? 'warm' : 'cold'}`, async ({ page, observations }, info) => {
    fault(info); allowed(observations, '/api/v1/destinations',503); let body: any;
    if (warm) body = await results(page);
    await page.route('**/api/v1/destinations?*', r => r.fulfill({ status: 503, json: { detail: 'E2E 목록 장애' } }));
    if (warm) await list(page).getByRole('button', { name: '목록 새로고침', exact: true }).click(); else await login(page,'/');
    await expect(list(page).getByRole('alert')).toBeVisible({ timeout:20000 });
    await expect(list(page).getByText('조건에 맞는 장소가 없습니다.')).toHaveCount(0);
    if (warm) await expect(rows(page)).toHaveCount(body.items.length);
    await page.unroute('**/api/v1/destinations?*');
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/destinations' && r.status() === 200);
    await list(page).getByRole('button', { name: warm ? '목록 새로고침' : '다시 시도', exact:true }).click(); await response;
    await expect(list(page).getByRole('alert')).toHaveCount(0); await expect(rows(page).first()).toBeVisible();
  });
}
test('장소의 빈 응답은 오류·이전 선택·이전 마커를 남기지 않는다', async ({ page },info) => {
  fault(info); await results(page); await rows(page).first().locator('button').first().click(); await expect(rows(page).first()).toHaveAttribute('data-selected','true');
  await page.route('**/api/v1/destinations?*', r => r.fulfill({json:{items:[],total:0,has_more:false,next_cursor:null}}));
  await page.getByLabel('장소 글자 검색').fill('E2E-empty');
  await expect(list(page).getByText('조건에 맞는 장소가 없습니다.')).toBeVisible();
  await expect(rows(page)).toHaveCount(0); await expect(page.locator('[data-interaction-id]')).toHaveCount(0); await expect(list(page).getByRole('alert')).toHaveCount(0);
});
async function review(page: Page) {
  const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/destinations/unmatched');
  await login(page,'/review'); const body=await(await response).json();expect(body.items.length).toBeGreaterThan(1);
  await page.getByRole('button',{name:'목록/관리',exact:true}).click();
  await expect(page.locator('tbody tr')).toHaveCount(body.items.length); return body;
}
test('검수 실제 후보 선택·checkbox·처리 모드의 identity를 보존한다', async ({page})=>{
  const body=await review(page);const row=page.locator('tbody tr').nth(1);
  await row.focus();await page.keyboard.press('Enter');await expect(row).toHaveAttribute('aria-selected','true');
  await row.getByRole('checkbox').check();await expect(row.getByRole('checkbox')).toBeChecked();
  await page.getByRole('button',{name:'처리 모드',exact:true}).click();await expect(page.locator('#main-content')).toContainText(body.items[1].ai_place_name);
  await page.getByRole('button',{name:'목록/관리',exact:true}).click();await expect(row).toHaveAttribute('aria-selected','true');
});
test('검수 도움말과 편집 focus에서는 단축키가 처리·후보 이동을 실행하지 않는다', async({page})=>{
  await review(page);const row=page.locator('tbody tr').nth(1);await row.focus();await page.keyboard.press('Space');await expect(row).toHaveAttribute('aria-selected','true');
  const help=page.getByRole('button',{name:'검수 단축키 도움말',exact:true});await help.click();
  await expect(page.getByRole('dialog',{name:'검수 단축키',exact:true})).toBeVisible();
  await page.keyboard.press('j');await page.keyboard.press('k');await page.keyboard.press('x');await expect(row).toHaveAttribute('aria-selected','true');
  await page.keyboard.press('Escape');await expect(help).toBeFocused();
  await page.getByLabel('외부 장소 검색어').focus();await page.keyboard.press('j');await page.keyboard.press('k');await expect(row).toHaveAttribute('aria-selected','true');
});
test('검수 검색은 실제 q 응답을 적용하고 필터를 새로고침 뒤 유지한다', async({page})=>{
  const body=await review(page);const q=body.items[0].ai_place_name;
  const response=page.waitForResponse(r=>{const u=new URL(r.url());return u.pathname==='/api/v1/destinations/unmatched'&&u.searchParams.get('q')===q});
  await page.getByLabel('검수 후보 검색').fill(q);const result=await(await response).json();expect(result.items.length).toBeGreaterThan(0);
  await expect(page.locator('tbody tr')).toHaveCount(result.items.length);await page.reload();await expect(page.getByLabel('검수 후보 검색')).toHaveValue(q);
});
test('검수 목록 첫 조회 오류를 표시하고 후보를 재조회한다',async({page,observations},info)=>{
  fault(info);allowed(observations,'/api/v1/destinations/unmatched',503);
  await page.route('**/api/v1/destinations/unmatched?*',r=>r.fulfill({status:503,json:{detail:'E2E 후보 오류'}}));await login(page,'/review');
  await page.getByRole('button',{name:'목록/관리',exact:true}).click();await expect(page.locator('#main-content aside').getByRole('alert').filter({hasText:'후보'})).toBeVisible({timeout:20000});
  await page.unroute('**/api/v1/destinations/unmatched?*');
  const restored=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/destinations/unmatched'&&r.status()===200);
  await page.locator('#main-content aside').getByRole('button',{name:'다시 시도',exact:true}).click();
  expect((await(await restored).json()).items.length).toBeGreaterThan(0);
  await expect(page.locator('tbody tr').first()).toBeVisible();await expect(page.getByRole('alert').filter({hasText:'후보'})).toHaveCount(0);
});

test('실제 다음 장소 page를 지연해 중복 요청·identity 중복·순번·선택 보존을 확인한다',async({page},info)=>{
  fault(info);const first=await results(page);expect(first.has_more).toBe(true);
  await rows(page).first().locator('button').first().click();let attempts=0;let route:import('@playwright/test').Route|undefined;let next:any;
  await page.route('**/api/v1/destinations?*',async r=>{
    const u=new URL(r.request().url());if(!u.searchParams.has('cursor'))return r.fallback();
    attempts++;expect(u.searchParams.get('limit')).toBe('100');expect(u.searchParams.get('cursor')).toBe(first.next_cursor);
    const response=await r.fetch();expect(response.status()).toBe(200);next=await response.json();route=r;
  });
  await list(page).getByRole('button',{name:'장소 더 불러오기',exact:true}).click();
  const busy=list(page).getByRole('button',{name:'불러오는 중…',exact:true});await expect(busy).toBeDisabled();await busy.evaluate((b:HTMLButtonElement)=>b.click());
  await expect.poll(()=>!!route).toBe(true);expect(attempts).toBe(1);await route!.fulfill({json:next});
  const ids=[...first.items,...next.items].map((i:any)=>i.place_id);expect(new Set(ids).size).toBe(ids.length);
  await expect(rows(page)).toHaveCount(ids.length);await expect(rows(page).first()).toHaveAttribute('data-selected','true');
  expect(await list(page).locator('[data-marker-number]').evaluateAll(nodes=>nodes.map(n=>Number(n.getAttribute('data-marker-number'))))).toEqual(ids.map((_:any,i:number)=>i+1));
});
test('검수 확정 폼의 숫자·빈 이름 경계를 검증하고 운영 저장을 보내지 않는다',async({page})=>{
  await review(page);await page.getByRole('button',{name:'처리 모드',exact:true}).click();
  await page.getByLabel('확정 장소명',{exact:true}).fill('E2E 미저장 장소');
  await page.getByLabel('위도',{exact:true}).fill('37.5');await page.getByLabel('경도',{exact:true}).fill('127');
  await expect(page.getByRole('button',{name:'저장',exact:true})).toBeEnabled();
  await page.getByLabel('위도',{exact:true}).fill('not-a-number');await expect(page.getByLabel('위도',{exact:true})).toHaveAttribute('aria-invalid','true');
  await expect(page.getByRole('alert').filter({hasText:'위도·경도'})).toBeVisible();await expect(page.getByRole('button',{name:'저장',exact:true})).toBeDisabled();
  await page.getByLabel('위도',{exact:true}).fill('37.5');
  await expect(page.getByRole('button',{name:'저장',exact:true})).toBeEnabled();
  await page.getByLabel('확정 장소명',{exact:true}).fill('');
  await expect(page.getByRole('button',{name:'저장',exact:true})).toBeDisabled();
  await page.getByLabel('확정 장소명',{exact:true}).fill('E2E 미저장 장소');await expect(page.getByRole('button',{name:'저장',exact:true})).toBeEnabled();
});
test('검수 synthetic IME 조합 중에는 검색 요청을 보내지 않는다',async({page},info)=>{
  fault(info);await review(page);const input=page.getByLabel('검수 후보 검색');let queries:string[]=[];
  page.on('request',r=>{const u=new URL(r.url());if(u.pathname==='/api/v1/destinations/unmatched'&&u.searchParams.has('q'))queries.push(u.searchParams.get('q')!)});
  await input.dispatchEvent('compositionstart');await input.fill('E2E조합');await page.waitForTimeout(600);expect(queries).toEqual([]);
  const response=page.waitForResponse(r=>{const u=new URL(r.url());return u.pathname==='/api/v1/destinations/unmatched'&&u.searchParams.get('q')==='E2E조합'});
  await input.dispatchEvent('compositionend');expect((await response).status()).toBe(200);expect(queries).toEqual(['E2E조합']);
});

test('늦은 장소 검색 A는 먼저 완료한 B의 목록과 마커를 덮지 않는다',async({page},info)=>{
  fault(info);const body=await results(page);let pending:import('@playwright/test').Route|undefined;
  const a={...body,items:[{...body.items[0],name:'E2E 늦은 A'}],total:1,has_more:false,next_cursor:null};
  const b={...body,items:[{...body.items[1],name:'E2E 최신 B'}],total:1,has_more:false,next_cursor:null};
  await page.route('**/api/v1/destinations?*',r=>{
    const q=new URL(r.request().url()).searchParams.get('q');
    if(q==='E2E-A'){pending=r;return;}if(q==='E2E-B')return r.fulfill({json:b});return r.fallback();
  });
  await page.getByLabel('장소 글자 검색').fill('E2E-A');await expect.poll(()=>!!pending).toBe(true);
  await page.getByLabel('장소 글자 검색').fill('E2E-B');await expect(rows(page)).toHaveCount(1);await expect(rows(page).first()).toContainText('E2E 최신 B');await expect(page.getByRole('button',{name:'1번 E2E 최신 B 선택',exact:true})).toHaveAttribute('data-selected','true');
  await expect(page.locator('.maplibregl-popup-content')).toContainText('E2E 최신 B');
  await expect(page.getByRole('button',{name:'1번 E2E 늦은 A 선택',exact:true})).toHaveCount(0);
  const response=page.waitForResponse(r=>new URL(r.url()).searchParams.get('q')==='E2E-A');await pending!.fulfill({json:a});await(await response).finished();
  // 늦은 query 완료 이후 React/cache 처리 시간을 의도적으로 확보한다.
  await page.waitForTimeout(350);await expect(rows(page).first()).toContainText('E2E 최신 B');await expect(list(page).getByText('E2E 늦은 A')).toHaveCount(0);await expect(page.getByRole('button',{name:'1번 E2E 최신 B 선택',exact:true})).toHaveAttribute('data-selected','true');
  await expect(page.locator('.maplibregl-popup-content')).toContainText('E2E 최신 B');
  await expect(page.getByRole('button',{name:'1번 E2E 늦은 A 선택',exact:true})).toHaveCount(0);
});
for(const mobile of [false,true]){
  test(`검수 후보 상세의 HTTP 오류와 재시도를 같은 ID로 확인한다 ${mobile?'mobile':'desktop'}`,async({page,observations},info)=>{
    fault(info);await page.setViewportSize({width:mobile?390:1440,height:1000});const body=await review(page);const item=body.items[0];const path=`/api/v1/destinations/candidates/${item.id}/detail`;allowed(observations,path,503);
    await page.route(`**${path}`,r=>r.fulfill({status:503,json:{detail:'E2E 상세 오류'}}));await page.locator('tbody tr').first().getByRole('button',{name:`${item.ai_place_name} 상세`,exact:true}).click();
    const area=mobile?page.locator('#main-content'):page.getByRole('dialog',{name:'검수 후보 상세',exact:true});
    if(mobile)await expect(page).toHaveURL(new RegExp(`/review/${item.id}$`));
    await expect(area.getByRole('alert').filter({hasText:'E2E 상세 오류'})).toBeVisible({timeout:20000});await page.unroute(`**${path}`);
    const restored=page.waitForResponse(r=>new URL(r.url()).pathname===path&&r.status()===200);await area.getByRole('button',{name:'다시 시도',exact:true}).click();
    const detail=await(await restored).json();expect(detail.list_item.id).toBe(item.id);await expect(area).toContainText(item.ai_place_name);await expect(area.getByRole('alert').filter({hasText:'E2E 상세 오류'})).toHaveCount(0);
  });
}
for(const text of ['[00:00] E2E 첫 문장\n[00:10] E2E 근거 문장','']){
  test(`출처 자막 UI의 원문·정리본과 빈 자막을 구분한다 ${text?'tabs':'empty'}`,async({page},info)=>{
    fault(info);const body=await results(page);const item=body.items[0];const path=`/api/v1/destinations/${item.place_id}/detail`;
    const response=page.waitForResponse(r=>new URL(r.url()).pathname===path);await rows(page).first().getByRole('button',{name:`${item.name} 상세`,exact:true}).click();
    const detail=await(await response).json();expect(detail.source_videos.length).toBeGreaterThan(0);const video=detail.source_videos[0];const transcript=`/api/v1/videos/${encodeURIComponent(video.video_id)}/transcript`;
    await page.route(`**${transcript}`,r=>r.fulfill({json:{kind:'corrected',text}}));const area=page.getByRole('dialog',{name:'장소 상세',exact:true});
    await area.getByRole('button',{name:/출처 동영상 상세$/}).first().click();
    if(text){await expect(area.getByRole('tab',{name:'타임스탬프 포함',exact:true})).toHaveAttribute('aria-selected','true');await expect(area.getByRole('tabpanel')).toContainText('[00:00]');
      await area.getByRole('tab',{name:'정리본',exact:true}).click();await expect(area.getByRole('tabpanel')).toContainText('E2E 첫 문장');await expect(area.getByRole('tabpanel')).not.toContainText('[00:00]');
      await expect(area.getByRole('button',{name:'근거 위치로 이동',exact:true})).toBeEnabled();
    }else{await expect(area.getByText('보정 자막 없음',{exact:true})).toBeVisible();await expect(area.getByRole('button',{name:'근거 위치로 이동',exact:true})).toBeDisabled();await expect(area.getByRole('tab')).toHaveCount(0);}
  });
}

test('페이지 밖 후보 딥링크는 전체 목록 순회 없이 단건 identity를 연다',async({page},info)=>{
  fault(info);const body=await review(page);const item=body.items[0];const actualPath=`/api/v1/destinations/candidates/${item.id}/detail`;
  const response=page.waitForResponse(r=>new URL(r.url()).pathname===actualPath);await page.locator('tbody tr').first().getByRole('button',{name:`${item.ai_place_name} 상세`,exact:true}).click();
  const detail=await(await response).json();await page.keyboard.press('Escape');
  const id=900099;const name='E2E 페이지 밖 후보';const clone=structuredClone(detail);clone.list_item.id=id;clone.list_item.ai_place_name=name;clone.candidate.id=id;clone.candidate.ai_place_name=name;
  expect(body.items.some((i:any)=>i.id===id)).toBe(false);let detailReads=0;let cursorReads=0;
  await page.route(`**/api/v1/destinations/candidates/${id}/detail`,r=>{detailReads++;return r.fulfill({json:clone})});
  page.on('request',r=>{const u=new URL(r.url());if(u.pathname==='/api/v1/destinations/unmatched'&&u.searchParams.has('cursor'))cursorReads++});
  await page.goto(`/review?candidate=${id}`,{waitUntil:'domcontentloaded'});await page.getByRole('button',{name:'처리 모드',exact:true}).click();
  await expect(page.locator('#main-content')).toContainText(name);await expect(page.getByText(/아직 불러온 페이지 밖 후보/)).toBeVisible();
  expect(detailReads).toBe(1);expect(cursorReads).toBe(0);await expect(page).toHaveURL(new RegExp(`candidate=${id}`));
});
