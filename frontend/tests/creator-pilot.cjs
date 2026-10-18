/**
 * Isolated UI regression: all /api requests use fictional fixtures; no LLM, ASR, or real account.
 * Start the frontend, then run:
 * VVA_PLAYWRIGHT_PACKAGE=/path/to/playwright VVA_BASE_URL=http://127.0.0.1:3007 node tests/creator-pilot.cjs
 * A locally installed playwright package also works without VVA_PLAYWRIGHT_PACKAGE.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.VVA_PLAYWRIGHT_PACKAGE || 'playwright');
const baseURL = process.env.VVA_BASE_URL || 'http://127.0.0.1:3007';
const output = process.env.VVA_OUTPUT_DIR ? path.resolve(process.env.VVA_OUTPUT_DIR) : path.resolve(__dirname, '../../output/soft-ui-20261018');
fs.mkdirSync(output, { recursive: true });
const timestamp = '2026-10-17T02:00:00Z';
const baseline = { id: 'fixture-job', query: '相机测评赛道：标题与开场的表达研究（演示）', platforms: ['bilibili'], analysis_mode: 'standard', status: 'running', progress: 35, clarification_round: 0, execution_version: 0, can_retry: false, can_revise: false, can_confirm_candidates: false, is_stopping: false, created_at: timestamp };
let job = { ...baseline };
let failuresRemaining = 0;
let failJobOnce = false;
let failEventsOnce = false;
let settleStopping = false;
let jobReads = 0;
let decisionsSubmitted = 0;
const creates = [];
const serverJobs = new Map();
const snapshot = {
  snapshot_id: 'fixture-snapshot', snapshot_version: 'candidate-snapshot.v1', snapshot_hash: 'a'.repeat(64), max_candidates: 8, can_submit: true,
  topic_spec: { topic: '相机测评', target_content: ['相机评测', '摄影器材使用'], competitor_definition: '持续发布相机测评的账号', time_window_days: 90, assumptions: [] },
  candidates: ['镜界研究所', '光圈手记', '器材观察站'].map((name, index) => ({ candidate_id: `candidate-${index}`, platform: 'bilibili', platform_account_id: String(1000 + index), display_name: `${name}（演示）`, profile_url: `https://space.bilibili.com/${1000 + index}`, source_evidence_ids: ['ev_a1b2c3d4'], matched_video_count: index + 2, sample_titles: ['演示样本：入门相机，先看这三个真实使用场景'], evidence_links: [{ evidence_id: 'ev_a1b2c3d4', title: '演示样本', source_url: 'https://www.bilibili.com/video/BV1demo' }], why_surfaced: ['样本标题与相机评测范围相符'], identity_confidence: 'high', decision: 'undecided', reason: '' })),
};
const evidence = [
  { evidence_id: 'ev_a1b2c3d4', tool: 'search_videos', source_type: 'bilibili_video', title: '入门相机，先看这三个真实使用场景（虚构演示）', source_url: 'https://www.bilibili.com/video/BV1demo', platform: 'bilibili', fetched_at: timestamp, summary: '此样本仅用于界面验证，不代表真实平台内容或市场数据。', data_fields: { author: '镜界研究所（演示）', bvid: 'BV1demo', view: 12500, like: 0, reply: null, favorite: 168, coin: null, share: 12, duration: 238, published_at: '2026-10-10T01:30:00Z' }, raw_data: {}, transcript_segment: null },
  { evidence_id: 'ev_e5f6a7b8', tool: 'get_transcript', source_type: 'transcript', title: '视频开场转写（虚构演示）', source_url: 'https://www.bilibili.com/video/BV1demo', platform: 'bilibili', fetched_at: timestamp, summary: '先展示拍摄场景，再提出比较问题。', data_fields: {}, raw_data: {}, transcript_segment: { text: '这三种拍摄场景，你更在乎哪一种？', segments: [{ start: 0, end: 8, text: '这三种拍摄场景，你更在乎哪一种？' }, { start: 8, end: 18, text: '我们先在相同条件下拍摄，再比较细节。' }] } },
];
evidence.push({ evidence_id: 'ev_knowledge', tool: 'rag_search', source_type: 'knowledge_base', title: '选题与观众问题（虚构知识参考）', platform: 'bilibili', fetched_at: timestamp, source_url: null, summary: '这是本地知识库中的方法参考，并非平台视频样本。', data_fields: {}, raw_data: {} });
const claims = [
  { claim: '演示样本的标题先交代使用场景，再给出比较范围。', claim_type: 'observation', confidence: 0.78, evidence_ids: ['ev_a1b2c3d4'] },
  { claim: '可以尝试让下一条选题从一个具体拍摄问题开始，并记录发布后的反馈。', claim_type: 'recommendation', confidence: 0.61, evidence_ids: ['ev_e5f6a7b8'] },
];
const report = { id: 'fixture-report', job_id: job.id, title: '从器材参数，到真实拍摄问题', status: 'partial', created_at: timestamp, updated_at: timestamp, model_info: {}, usage: { input_tokens: 3200, output_tokens: 1500, estimated_cost: 0.018, asr_seconds: 18 }, evidence, structured_claims: claims,
  content: '# 从器材参数，到真实拍摄问题\n\n> 本报告为本地界面演示。样本、账号和数值均为虚构，不构成实际市场结论。\n\n## 先看见使用场景\n\n演示样本把观众会遇到的问题放在前面，再解释器材如何参与解决。这让标题中的承诺更具体。 [ev_a1b2c3d4]\n\n## 下一条内容可以怎样尝试\n\n从“旅行拍人像时，我遇到了什么问题”开始，先展示场景，再说明判断依据。把这个方向作为一次小范围验证。 [ev_e5f6a7b8]\n\n## 结构化结论与引用\n\n1. **数据观察**：演示样本的标题先交代使用场景，再给出比较范围。 [ev_a1b2c3d4]\n2. **行动建议**：下一条选题从一个具体拍摄问题开始。 [ev_e5f6a7b8]\n\n## 数据附录（程序生成）\n\n| 样本 | 播放 | 点赞 | 评论 |\n|---|---:|---:|---|\n| 虚构演示样本 | 12500 | 0 | 未提供 |\n\n> 局限：结论只适用于本次样本，不代表全平台规律。',
};
const checks = [];
const pageErrors = [];
const contrastResults = {};
function pass(name) { checks.push(name); console.log(`PASS ${name}`); }
(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.VVA_BROWSER_EXECUTABLE ? { executablePath: process.env.VVA_BROWSER_EXECUTABLE } : {}) });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', reducedMotion: 'reduce' });
    await context.addCookies([{ name: 'viral_video_session', value: 'fictional-ui-fixture', url: baseURL }]);
    await context.route('**/api/**', async (route) => {
      const request = route.request(); const url = new URL(request.url()); const endpoint = url.pathname.slice(4);
      const json = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
      if (endpoint === '/capabilities') return json({ items: [{ name: 'get_transcript', enabled: true }], platforms: ['bilibili'] });
      if (endpoint === '/usage') return json({ jobs_used: 9, jobs_limit: 30, input_tokens: 3200, output_tokens: 1500, estimated_cost: 0.018, asr_seconds: 18 });
      if (endpoint === '/jobs' && request.method() === 'POST') {
        const body = request.postDataJSON(); creates.push(body);
        if (!serverJobs.has(body.idempotency_key)) serverJobs.set(body.idempotency_key, { ...baseline, query: body.query });
        if (failuresRemaining-- > 0) return route.abort('failed');
        job = serverJobs.get(body.idempotency_key); return json(job, 202);
      }
      if (endpoint === '/jobs') {
        const status = url.searchParams.get('status');
        const waiting = { ...baseline, status: 'waiting_candidate_confirmation', progress: 55, can_confirm_candidates: true, can_revise: true };
        return json({ items: !status ? [waiting, { ...baseline, id: 'fixture-completed', query: 'AI 编程教程：选题与标题观察（演示）', status: 'completed', progress: 100, report_id: report.id }] : status === 'waiting_candidate_confirmation' ? [waiting] : [], total: !status ? 2 : status === 'waiting_candidate_confirmation' ? 1 : 0 });
      }
      if (endpoint === '/jobs/fixture-job') {
        jobReads++;
        if (failJobOnce) { failJobOnce = false; return route.abort('failed'); }
        if (job.is_stopping && settleStopping) job = { ...job, is_stopping: false, can_retry: true, can_revise: true };
        return json(job);
      }
      if (endpoint.endsWith('/events')) {
        if (failEventsOnce) { failEventsOnce = false; return route.abort('failed'); }
        return json({ items: [{ event_type: job.status === 'waiting_candidate_confirmation' ? 'waiting_candidate_confirmation' : 'collecting', message: job.status === 'waiting_candidate_confirmation' ? '样本已整理完成，等待你确认账号范围。' : '正在整理本次研究的公开样本。', progress: job.progress, level: 'info', created_at: timestamp }] });
      }
      if (endpoint.endsWith('/candidates')) return json(snapshot);
      if (endpoint.endsWith('/candidates/decisions')) { decisionsSubmitted++; job = { ...job, status: 'pending', progress: 60, can_confirm_candidates: false }; return json(job, 202); }
      if (endpoint === '/reports/fixture-report' || endpoint === '/shares/fixture-token') return json(report);
      if (endpoint.endsWith('/feedback')) return route.fulfill({ status: 204 });
      if (endpoint.endsWith('/shares')) return json({ token: 'fixture-token', id: 'fixture-share', expires_at: '2026-10-24T02:00:00Z' }, 201);
      if (endpoint.endsWith('/cancel')) { job = { ...job, status: 'cancelled', is_stopping: true, can_retry: false }; return json(job); }
      if (endpoint === '/auth/me') return json({ id: 'fixture-user', email: 'demo@example.invalid', created_at: timestamp, is_active: true });
      throw new Error(`Unexpected API request: ${request.method()} ${endpoint}`);
    });
    const page = await context.newPage(); page.on('pageerror', (error) => pageErrors.push(error.message));
    const screenshots = [];
    const settleLayout = () => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const screenshot = async (name, fullPage = true) => { await page.evaluate(() => document.fonts.ready); if (fullPage) await page.evaluate(() => scrollTo(0, 0)); await settleLayout(); screenshots.push(name); return page.screenshot({ path: path.join(output, name), fullPage, animations: 'disabled' }); };
    const fit = async (name) => { await settleLayout(); const size = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, viewport: innerWidth })); if (size.scroll > size.viewport) { console.log('OVERFLOW', await page.evaluate(() => Array.from(document.querySelectorAll('body *')).filter((el) => el.getBoundingClientRect().right > innerWidth + 1).map((el) => ({ tag: el.tagName, className: el.className, width: el.getBoundingClientRect().width, text: el.textContent?.slice(0, 70) })).slice(-30))); await screenshot('overflow-debug.png'); } assert.ok(size.scroll <= size.viewport, `${name} overflow: ${JSON.stringify(size)}`); };
    const checkContrast = async (theme) => {
      const results = await page.evaluate(() => {
        const probe = document.createElement('span'); probe.style.setProperty('transition', 'none', 'important'); document.body.appendChild(probe);
        const color = (token) => { probe.style.color = `hsl(var(--${token}))`; return getComputedStyle(probe).color.match(/[\d.]+/g).slice(0, 3).map(Number); };
        const luminance = (rgb) => rgb.map((v) => { const c = v / 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; }).reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
        const pairs = [['foreground', 'background', 4.5], ['muted-foreground', 'card', 4.5], ['muted-foreground', 'muted', 4.5], ['primary', 'card', 4.5], ['primary-foreground', 'primary', 4.5], ['input', 'surface-elevated', 3]];
        const values = pairs.map(([fg, bg, minimum]) => { const a = luminance(color(fg)); const b = luminance(color(bg)); return { pair: `${fg}/${bg}`, ratio: (Math.max(a, b) + .05) / (Math.min(a, b) + .05), minimum }; });
        probe.remove(); return values;
      });
      for (const item of results) assert.ok(item.ratio >= item.minimum, `${theme}: ${item.pair} contrast ${item.ratio}`);
      contrastResults[theme] = results;
    };
    await page.goto(baseURL); await page.getByRole('heading', { name: /让真实样本/ }).waitFor();
    await page.getByRole('button', { name: '切换到深色主题' }).waitFor();
    assert.equal(await page.locator('html').evaluate((el) => el.classList.contains('light')), true);
    await checkContrast('light'); await fit('home light'); await screenshot('home-desktop-light.png'); await screenshot('home-hero-light.png', false);
    await page.setViewportSize({ width: 375, height: 812 }); await fit('home light mobile'); await screenshot('home-mobile-light.png');
    await page.setViewportSize({ width: 768, height: 1024 }); await fit('home tablet');
    await page.evaluate(() => document.documentElement.style.fontSize = '200%'); await fit('home enlarged text');
    await page.evaluate(() => document.documentElement.style.fontSize = '');
    pass('light default, tablet and enlarged text layouts');
    await page.getByRole('button', { name: '切换到深色主题' }).click(); await page.reload();
    await page.getByRole('button', { name: '切换到浅色主题' }).waitFor(); await checkContrast('dark');
    pass('saved dark preference persists; light and dark text and input contrast pass');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await fit('home desktop'); await screenshot('home-desktop-dark.png'); await screenshot('home-hero-dark.png', false);
    await page.setViewportSize({ width: 375, height: 812 }); await fit('home mobile'); await screenshot('home-mobile-dark.png');
    await page.getByRole('button', { name: '打开导航菜单' }).click();
    await page.getByRole('navigation', { name: '移动端公共导航' }).getByRole('link', { name: /分析模板/ }).click();
    await page.getByRole('dialog', { name: '移动导航' }).waitFor({ state: 'hidden' }); pass('mobile hash navigation closes drawer');
    await page.getByRole('button', { name: '打开导航菜单' }).click();
    await page.getByRole('button', { name: '关闭导航菜单' }).waitFor(); await page.keyboard.press('Escape');
    await page.getByRole('dialog', { name: '移动导航' }).waitFor({ state: 'hidden' });
    assert.equal(await page.getByRole('button', { name: '打开导航菜单' }).evaluate((el) => el === document.activeElement), true);
    pass('mobile navigation Escape returns focus to its trigger');
    await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto(`${baseURL}/dashboard`);
    await page.getByRole('heading', { name: '最近的研究' }).waitFor(); await fit('dashboard desktop'); await screenshot('dashboard-desktop-dark.png');
    await page.getByRole('button', { name: '切换到浅色主题' }).click(); await settleLayout(); await screenshot('dashboard-desktop-light.png');
    await page.setViewportSize({ width: 320, height: 740 }); await fit('dashboard 320px');
    await page.setViewportSize({ width: 375, height: 812 }); await screenshot('dashboard-mobile-light.png');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${baseURL}/jobs/new`); await page.getByLabel('你的研究问题', { exact: false }).fill('分析B站近30天相机评测，比较标题和开场。');
    assert.equal(await page.locator('#analysis-query').evaluate((el) => getComputedStyle(el).backgroundColor), 'rgb(255, 255, 255)');
    await fit('new job desktop'); await screenshot('new-job-desktop-light.png');
    await page.setViewportSize({ width: 320, height: 740 }); await fit('new job 320px');
    await page.setViewportSize({ width: 375, height: 812 }); await screenshot('new-job-mobile-light.png');
    await page.setViewportSize({ width: 1440, height: 1000 }); await settleLayout(); pass('new inquiry form fits a 320px viewport');
    failuresRemaining = 2;
    await page.getByRole('button', { name: '开始研究', exact: true }).click();
    await page.getByRole('button', { name: '重试这次提交' }).waitFor();
    await page.getByRole('button', { name: '重试这次提交' }).click();
    await page.getByRole('button', { name: '重试这次提交' }).waitFor();
    await page.reload(); await page.waitForFunction(() => document.querySelector('#analysis-query')?.value === '分析B站近30天相机评测，比较标题和开场。');
    await page.getByRole('button', { name: '开始研究', exact: true }).click(); await page.waitForURL('**/jobs/fixture-job');
    assert.equal(creates.length, 3); assert.equal(new Set(creates.map((item) => item.idempotency_key)).size, 1); assert.equal(serverJobs.size, 1); pass('lost creation responses reuse one idempotency key, including after reload');
    await screenshot('job-progress-desktop-light.png'); pass('unresolved submission restores the query after reload');
    job = { ...baseline, status: 'waiting_candidate_confirmation', progress: 55, can_confirm_candidates: true, can_revise: true };
    await page.reload(); await page.getByRole('heading', { name: '哪些账号值得放在一起研究？' }).waitFor();
    await screenshot('candidates-desktop-light.png');
    const fieldsets = page.locator('fieldset'); await fieldsets.nth(0).getByRole('radio', { name: /纳入分析/ }).check();
    await fieldsets.nth(0).getByText('添加简短原因（可选）', { exact: true }).click(); await fieldsets.nth(0).getByRole('textbox').fill('与本次评测范围一致');
    failEventsOnce = true; await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await page.getByRole('button', { name: '重新连接' }).waitFor(); assert.equal(await fieldsets.nth(0).getByRole('radio', { name: /纳入分析/ }).isChecked(), true); assert.equal(await fieldsets.nth(0).getByRole('textbox').inputValue(), '与本次评测范围一致');
    failJobOnce = true; await page.getByRole('button', { name: '重新连接' }).click(); await page.waitForTimeout(300); assert.equal(await fieldsets.nth(0).getByRole('radio', { name: /纳入分析/ }).isChecked(), true);
    await page.getByRole('button', { name: '重新连接' }).click(); await page.getByRole('button', { name: '重新连接' }).waitFor({ state: 'hidden' });
    await page.reload(); await page.getByRole('heading', { name: '哪些账号值得放在一起研究？' }).waitFor(); await page.waitForFunction(() => document.querySelector('input[value="confirmed"]')?.checked);
    assert.equal(await fieldsets.nth(0).getByRole('textbox').inputValue(), '与本次评测范围一致'); pass('candidate choices and reasons survive failed polling and reload');
    await page.getByRole('button', { name: '确认并继续', exact: true }).click(); await page.waitForFunction(() => document.activeElement?.getAttribute('name') === 'candidate-candidate-1'); pass('missing candidate decision receives keyboard focus');
    await fieldsets.nth(1).getByRole('radio', { name: /^排除/ }).check(); await fieldsets.nth(2).getByRole('radio', { name: /^不确定/ }).check();
    await page.setViewportSize({ width: 375, height: 812 }); await page.getByRole('button', { name: '切换到深色主题' }).click(); await fit('candidate mobile'); await screenshot('candidates-mobile-dark.png');
    await page.getByRole('button', { name: '确认并继续', exact: true }).click(); await page.getByRole('heading', { name: '哪些账号值得放在一起研究？' }).waitFor({ state: 'hidden' }); assert.equal(decisionsSubmitted, 1); pass('candidate submission resumes the existing job once');
    settleStopping = false;
    await page.getByRole('button', { name: '取消任务', exact: true }).click();
    await page.getByText('正在停止并保存本次用量。完成后，这里会更新可用操作。', { exact: true }).waitFor();
    settleStopping = true;
    await page.getByRole('button', { name: '重试任务', exact: true }).waitFor({ timeout: 15000 }); const stoppedAt = jobReads; await page.waitForTimeout(4000); assert.equal(jobReads, stoppedAt); pass('cancelled job keeps polling while stopping, then stops after settlement');
    job = { ...job, can_retry: false, can_revise: true }; await page.reload();
    await page.getByText('任务已取消，已产生的用量会保留。可修改研究范围创建新任务。', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '重试任务', exact: true }).count(), 0); pass('cancelled copy respects the server retry limit');
    await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto(`${baseURL}/reports/fixture-report`); await page.getByRole('heading', { name: report.title }).first().waitFor();
    assert.equal(await page.locator('#report-claims').getAttribute('open'), null); assert.equal(await page.locator('#report-evidence').getAttribute('open'), null);
    await screenshot('report-desktop-dark.png'); await page.getByRole('button', { name: '切换到浅色主题' }).click(); await screenshot('report-desktop-light.png');
    await page.locator('.report-prose').getByRole('link', { name: '[ev_a1b2c3d4]', exact: true }).first().click();
    assert.equal(await page.locator('#report-evidence').evaluate((el) => el.open), true);
    const evidenceCard = page.locator('#ev_a1b2c3d4');
    const value = (label) => evidenceCard.locator('dl > div').filter({ has: page.locator('dt').getByText(label, { exact: true }) }).locator('dd').innerText();
    assert.equal(await value('点赞'), '0'); assert.equal(await value('评论'), '未提供'); assert.notEqual(await value('发布时间'), '未提供'); assert.notEqual(await value('采集时间'), '未提供');
    const knowledgeCard = page.locator('#ev_knowledge'); await knowledgeCard.getByText('知识参考', { exact: true }).waitFor();
    assert.equal(await knowledgeCard.locator('dt').getByText('播放', { exact: true }).count(), 0);
    await screenshot('evidence-desktop-light.png'); pass('citation opens evidence; actual zero, missing values, published and fetched time stay distinct'); pass('Bilibili knowledge references are not classified as video samples');
    await page.getByRole('link', { name: '核对结论 · 2', exact: true }).click(); await page.getByText('模型自评 78%', { exact: true }).waitFor(); pass('confidence is labeled as uncalibrated model self-assessment');
    await page.setViewportSize({ width: 320, height: 740 }); await fit('report 320px'); pass('expanded report and evidence fit a 320px viewport');
    await page.locator('#report-claims > summary').click(); await page.locator('#report-evidence > summary').click();
    await page.setViewportSize({ width: 375, height: 812 }); await screenshot('report-mobile-light.png');
    await page.getByRole('button', { name: '切换到深色主题' }).click(); await settleLayout(); await page.emulateMedia({ media: 'print' }); await settleLayout(); assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor), 'rgb(255, 255, 255)');
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor), 'rgb(255, 255, 255)');
    assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme), 'light');
    assert.equal(await page.locator('#report-evidence').evaluate((el) => getComputedStyle(el).display), 'none');
    assert.equal(await page.locator('#report-claims').evaluate((el) => getComputedStyle(el).display), 'none');
    await page.pdf({ path: path.join(output, 'report-print-from-dark.pdf'), format: 'A4', printBackground: true }); await page.emulateMedia({ media: 'screen' }); pass('dark theme printing uses light paper tokens and hides duplicate detail panels');
    await page.goto(`${baseURL}/reports/fixture-report#ev_a1b2c3d4`); await page.reload();
    await page.waitForFunction(() => { const card = document.getElementById('ev_a1b2c3d4'); const top = card?.getBoundingClientRect().top; return document.getElementById('report-evidence')?.open && typeof top === 'number' && top >= -1 && top < 180; }); pass('initial evidence deep links expand and scroll after asynchronous report load');
    await page.goto(`${baseURL}/login?next=${encodeURIComponent('/jobs/new?template=竞品账号内容拆解')}`); const registerLink = page.getByRole('link', { name: '注册公开测试账号', exact: true }); await registerLink.waitFor(); await page.waitForFunction(() => document.querySelector('a[href^="/register?next="]')?.getAttribute('href')?.includes('%2Fjobs%2Fnew'));
    await registerLink.click(); await page.waitForURL((url) => url.pathname === '/register');
    const destination = new URL(new URL(page.url()).searchParams.get('next'), baseURL);
    assert.equal(destination.pathname, '/jobs/new'); assert.equal(destination.searchParams.get('template'), '竞品账号内容拆解'); pass('login-to-registration preserves the selected template destination');
    await page.getByRole('button', { name: '切换到浅色主题' }).click();
    await page.setViewportSize({ width: 320, height: 740 }); await fit('registration 320px');
    await page.setViewportSize({ width: 375, height: 812 }); await screenshot('register-mobile-light.png');
    await page.setViewportSize({ width: 1440, height: 1000 }); await screenshot('register-desktop-light.png');
    await page.goto(`${baseURL}/examples`); await page.getByRole('heading', { name: '先看清证据如何进入报告' }).waitFor(); await screenshot('examples-desktop-light.png');
    pass('registration and public examples render in the new theme');
    assert.deepEqual(pageErrors, []); pass('no unhandled browser page errors');
    fs.writeFileSync(path.join(output, 'ui-validation.json'), JSON.stringify({ fixtureOnly: true, executedAt: new Date().toISOString(), platform: process.platform, browser: await browser.version(), checks, pageErrors, contrastResults, screenshots }, null, 2));
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
