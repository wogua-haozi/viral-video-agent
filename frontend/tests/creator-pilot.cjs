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
let activeUserId = 'fixture-user';
let revisionOutcome = 'ok';
let retryOutcome = 'ok';
let retryRequests = 0;
let retryStateReads = null;
let retryCommitAfterReads = null;
let blockJobReads = false;
const staleRetryReads = [];
const creates = [];
const serverJobs = new Map();
const revisions = [];
const revisionJobs = new Map();
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
      if (/^\/jobs\/fixture-(job|other)\/revisions$/.test(endpoint)) {
        const body = request.postDataJSON();
        const sourceId = endpoint.split('/')[2];
        const key = JSON.stringify([activeUserId, sourceId, body.idempotency_key]);
        revisions.push({ ...body, userId: activeUserId, sourceId });
        if (!revisionJobs.has(key)) revisionJobs.set(key, { ...baseline, id: `fixture-revision-${revisionJobs.size + 1}`, query: body.query, revision_of_job_id: sourceId, status: 'pending', progress: 0 });
        if (revisionOutcome === 'lost') return route.abort('failed');
        if (revisionOutcome === '503') return json({ error_code: 'WORKER_FAILED', message: '演示：修订响应暂不可用。' }, 503);
        return json(revisionJobs.get(key), 202);
      }
      if (endpoint === '/jobs/fixture-job/retry') {
        retryRequests++;
        if (retryOutcome === 'rejected') return json({ error_code: 'JOB_RETRY_LIMIT_REACHED', message: '演示：这个任务已达到重试上限。' }, 409);
        if (retryOutcome === 'delayed' || retryOutcome === 'unconfirmed') {
          retryCommitAfterReads = retryOutcome === 'delayed' ? 3 : Infinity;
          return route.abort('failed');
        }
        if (retryOutcome === 'blocked408') {
          retryCommitAfterReads = Infinity; failJobOnce = true; blockJobReads = true;
          return json({ error_code: 'REQUEST_FAILED', message: '演示：代理请求超时，结果未知。' }, 408);
        }
        job = { ...job, status: 'pending', progress: 0, execution_version: job.execution_version + 1, can_retry: false, can_revise: false };
        retryStateReads = 0;
        if (retryOutcome === 'lost') return route.abort('failed');
        if (retryOutcome === '503') { failJobOnce = true; return json({ error_code: 'WORKER_FAILED', message: '演示：重试响应暂不可用。' }, 503); }
        return json(job, 202);
      }
      if (endpoint === '/jobs') {
        const status = url.searchParams.get('status');
        const waiting = { ...baseline, status: 'waiting_candidate_confirmation', progress: 55, can_confirm_candidates: true, can_revise: true };
        return json({ items: !status ? [waiting, { ...baseline, id: 'fixture-completed', query: 'AI 编程教程：选题与标题观察（演示）', status: 'completed', progress: 100, report_id: report.id }] : status === 'waiting_candidate_confirmation' ? [waiting] : [], total: !status ? 2 : status === 'waiting_candidate_confirmation' ? 1 : 0 });
      }
      if (endpoint === '/jobs/fixture-job') {
        jobReads++;
        if (failJobOnce) { failJobOnce = false; return route.abort('failed'); }
        // Leave the request unresolved to verify the confirmation deadline also
        // works when the network never returns a response.
        if (blockJobReads) return;
        if (job.is_stopping && settleStopping) job = { ...job, is_stopping: false, can_retry: true, can_revise: true };
        if (retryCommitAfterReads !== null) {
          if (retryCommitAfterReads > 0) {
            staleRetryReads.push({ status: job.status, execution_version: job.execution_version });
            retryCommitAfterReads--;
            return json(job);
          }
          retryCommitAfterReads = null;
          job = { ...job, status: 'pending', progress: 0, execution_version: job.execution_version + 1, can_retry: false, can_revise: false };
          retryStateReads = 0;
        }
        if (retryStateReads !== null) {
          retryStateReads++;
          if (retryStateReads === 2) job = { ...job, status: 'running', progress: 50 };
          if (retryStateReads >= 3) { job = { ...job, status: 'completed', progress: 100 }; retryStateReads = null; }
        }
        return json(job);
      }
      if (endpoint === '/jobs/fixture-other') return json({ ...job, id: 'fixture-other' });
      if (/^\/jobs\/fixture-revision-\d+$/.test(endpoint)) return json([...revisionJobs.values()].find((item) => `/jobs/${item.id}` === endpoint));
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
      if (endpoint === '/auth/me') return json({ id: activeUserId, email: 'demo@example.invalid', created_at: timestamp, is_active: true });
      throw new Error(`Unexpected API request: ${request.method()} ${endpoint}`);
    });
    const page = await context.newPage(); page.on('pageerror', (error) => pageErrors.push(error.message));
    const mediaSession = await context.newCDPSession(page);
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
    const reducedTransparency = async (reduce) => {
      await mediaSession.send('Emulation.setEmulatedMedia', { media: 'screen', features: [
        { name: 'prefers-reduced-motion', value: 'reduce' },
        { name: 'prefers-reduced-transparency', value: reduce ? 'reduce' : 'no-preference' },
      ] });
      assert.equal(await page.evaluate((expected) => matchMedia(`(prefers-reduced-transparency: ${expected})`).matches, reduce ? 'reduce' : 'no-preference'), true);
      assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true);
      await settleLayout();
    };
    const checkMaterial = async (locator, opaque) => {
      const style = await locator.evaluate((element) => {
        const css = getComputedStyle(element);
        const channels = css.backgroundColor.match(/[\d.]+/g).map(Number);
        return { backdrop: css.backdropFilter, webkitBackdrop: css.getPropertyValue('-webkit-backdrop-filter'), alpha: channels[3] ?? 1 };
      });
      assert.equal(style.backdrop, 'none');
      if (style.webkitBackdrop) assert.equal(style.webkitBackdrop, 'none');
      assert.ok(opaque ? style.alpha === 1 : style.alpha >= 0.7, `reduced transparency fill: ${JSON.stringify(style)}`);
    };
    const checkDrawerKeyboard = async (dialog) => {
      const selector = 'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';
      const count = await dialog.evaluate((element, query) => {
        const controls = Array.from(element.querySelectorAll(query)).filter((node) => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden');
        controls[0]?.focus(); return controls.length;
      }, selector);
      assert.ok(count >= 2, 'drawer must expose keyboard-accessible controls');
      await page.keyboard.press('Shift+Tab');
      assert.equal(await dialog.evaluate((element, query) => {
        const controls = Array.from(element.querySelectorAll(query)).filter((node) => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden');
        return document.activeElement === controls[controls.length - 1];
      }, selector), true);
      await page.keyboard.press('Tab');
      assert.equal(await dialog.evaluate((element, query) => {
        const controls = Array.from(element.querySelectorAll(query)).filter((node) => node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden');
        const active = document.activeElement;
        const css = getComputedStyle(active);
        const bounds = active.getBoundingClientRect();
        return active === controls[0] && active.matches(':focus-visible') &&
          (css.boxShadow !== 'none' || (css.outlineStyle !== 'none' && parseFloat(css.outlineWidth) > 0)) &&
          bounds.left >= 0 && bounds.right <= innerWidth + 1 && bounds.top >= 0 && bounds.bottom <= innerHeight + 1;
      }, selector), true);
    };
    await page.goto(baseURL); await page.getByRole('heading', { name: /让真实样本/ }).waitFor();
    await page.getByRole('button', { name: '切换到深色主题' }).waitFor();
    assert.equal(await page.locator('html').evaluate((el) => el.classList.contains('light')), true);
    await checkContrast('light'); await fit('home light'); await screenshot('home-desktop-light.png'); await screenshot('home-hero-light.png', false);
    await page.setViewportSize({ width: 375, height: 812 }); await fit('home light mobile'); await screenshot('home-mobile-light.png');
    await page.setViewportSize({ width: 768, height: 1024 }); await fit('home tablet');
    const homeRootFontSize = await page.locator('html').evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
    await page.evaluate(() => document.documentElement.style.fontSize = '200%');
    await page.waitForFunction((baseline) => parseFloat(getComputedStyle(document.documentElement).fontSize) >= baseline * 1.99, homeRootFontSize);
    await fit('home enlarged text');
    await page.evaluate(() => document.documentElement.style.fontSize = '');
    await page.waitForFunction((baseline) => Math.abs(parseFloat(getComputedStyle(document.documentElement).fontSize) - baseline) < 0.01, homeRootFontSize);
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
    await page.getByRole('button', { name: '关闭导航菜单' }).waitFor();
    const publicDrawer = page.getByRole('dialog', { name: '移动导航' });
    await settleLayout();
    const motion = await publicDrawer.locator('.motion-enter').evaluate((element) => {
      const css = getComputedStyle(element);
      const control = getComputedStyle(element.querySelector('button'));
      const milliseconds = (list) => list.split(',').map((value) => parseFloat(value) * (value.trim().endsWith('ms') ? 1 : 1000));
      return {
        preference: matchMedia('(prefers-reduced-motion: reduce)').matches,
        animation: milliseconds(css.animationDuration), transition: milliseconds(control.transitionDuration),
        scroll: getComputedStyle(document.documentElement).scrollBehavior, opacity: css.opacity,
      };
    });
    assert.equal(motion.preference, true); assert.equal(motion.scroll, 'auto'); assert.equal(motion.opacity, '1');
    assert.ok([...motion.animation, ...motion.transition].every((duration) => duration <= 0.01), JSON.stringify(motion));
    pass('reduced motion disables actual drawer animation, control transitions and smooth scrolling');
    await reducedTransparency(true);
    await checkMaterial(page.locator('header.navigation-material'), true); await checkMaterial(publicDrawer, false);
    await checkDrawerKeyboard(publicDrawer);
    await page.keyboard.press('Escape');
    await page.getByRole('dialog', { name: '移动导航' }).waitFor({ state: 'hidden' });
    assert.equal(await page.getByRole('button', { name: '打开导航菜单' }).evaluate((el) => el === document.activeElement), true);
    pass('mobile navigation Escape returns focus to its trigger');
    await reducedTransparency(false);
    await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto(`${baseURL}/dashboard`);
    await page.getByRole('heading', { name: '最近的研究' }).waitFor(); await fit('dashboard desktop'); await screenshot('dashboard-desktop-dark.png');
    await page.getByRole('button', { name: '切换到浅色主题' }).click(); await settleLayout(); await screenshot('dashboard-desktop-light.png');
    await page.setViewportSize({ width: 320, height: 740 }); await fit('dashboard 320px');
    await reducedTransparency(true); await page.getByRole('button', { name: '打开菜单', exact: true }).click();
    const workspaceDrawer = page.getByRole('dialog', { name: '工作台移动导航' });
    await workspaceDrawer.waitFor(); await checkMaterial(page.locator('header.navigation-material'), true); await checkMaterial(workspaceDrawer, false);
    await checkDrawerKeyboard(workspaceDrawer); await page.keyboard.press('Escape'); await workspaceDrawer.waitFor({ state: 'hidden' });
    assert.equal(await page.getByRole('button', { name: '打开菜单', exact: true }).evaluate((element) => element === document.activeElement), true);
    pass('public and workspace drawers trap Tab in both directions and restore visible trigger focus');
    await reducedTransparency(false);
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
    const revisionA = '只看相机评测的标题结构（演示修订 A）';
    const revisionB = '只看相机评测的开场结构（演示修订 B）';
    const revisionInput = page.getByLabel('新的研究范围', { exact: true });
    const submitRevision = page.getByRole('button', { name: '创建修订任务', exact: true });
    const waitRevision = async (query) => page.waitForFunction((expected) => {
      const input = document.querySelector('#revision-query');
      return input && !input.disabled && input.value === expected;
    }, query);
    await page.goto(`${baseURL}/jobs/fixture-job?revise=1`);
    await waitRevision(job.query);
    revisionOutcome = '503';
    await revisionInput.fill(revisionA); await submitRevision.click();
    await page.getByRole('alert').getByText('演示：修订响应暂不可用。', { exact: true }).waitFor();
    await page.reload(); await waitRevision(revisionA);
    revisionOutcome = 'lost';
    await submitRevision.click(); await page.getByRole('alert').getByText('网络异常，请检查连接后重试。', { exact: true }).waitFor();
    assert.equal(revisions.length, 2); assert.equal(revisions[0].idempotency_key, revisions[1].idempotency_key); assert.equal(revisionJobs.size, 1);
    pass('revision 503 and lost responses reuse the persisted payload and key after reload');
    await revisionInput.fill(revisionB); await submitRevision.click();
    await page.getByRole('alert').getByText('网络异常，请检查连接后重试。', { exact: true }).waitFor();
    assert.notEqual(revisions[2].idempotency_key, revisions[0].idempotency_key);
    await page.reload(); await waitRevision(revisionB);
    activeUserId = 'fixture-other-user';
    await page.reload(); await waitRevision(job.query);
    await revisionInput.fill(revisionB); await submitRevision.click();
    await page.getByRole('alert').getByText('网络异常，请检查连接后重试。', { exact: true }).waitFor();
    assert.notEqual(revisions[3].idempotency_key, revisions[2].idempotency_key);
    await page.goto(`${baseURL}/jobs/fixture-other?revise=1`); await waitRevision(job.query);
    activeUserId = 'fixture-user';
    await page.goto(`${baseURL}/jobs/fixture-job?revise=1`); await waitRevision(revisionB);
    pass('unresolved revision drafts are isolated by account and source job');
    revisionOutcome = 'ok';
    await revisionInput.fill(revisionA); await submitRevision.click(); await page.waitForURL('**/jobs/fixture-revision-1');
    assert.equal(revisions[4].idempotency_key, revisions[0].idempotency_key); assert.equal(revisionJobs.size, 3);
    await page.goto(`${baseURL}/jobs/fixture-job?revise=1`); await waitRevision(revisionB);
    await submitRevision.click(); await page.waitForURL('**/jobs/fixture-revision-2');
    assert.equal(revisions[5].idempotency_key, revisions[2].idempotency_key);
    await page.goto(`${baseURL}/jobs/fixture-job?revise=1`); await waitRevision(job.query);
    activeUserId = 'fixture-other-user'; await page.reload(); await waitRevision(revisionB);
    activeUserId = 'fixture-user';
    pass('editing a revision and restoring an earlier payload reuses its key; success clears only that attempt');
    for (const outcome of ['503', 'lost']) {
      job = { ...baseline, status: 'failed', progress: 0, can_retry: true, can_revise: true };
      retryOutcome = outcome;
      await page.goto(`${baseURL}/jobs/fixture-job`); await page.getByRole('button', { name: '重试任务', exact: true }).waitFor();
      const requestsBefore = retryRequests;
      await page.getByRole('button', { name: '重试任务', exact: true }).click();
      await page.getByText('研究记录已保存。', { exact: true }).waitFor({ timeout: 20000 });
      assert.equal(retryRequests, requestsBefore + 1); assert.equal(job.execution_version, 1); assert.equal(job.status, 'completed');
      // Next.js also renders an empty route-announcement alert outside main.
      assert.equal(await page.getByRole('main').getByRole('alert').count(), 0);
      const completedAt = jobReads; await page.waitForTimeout(4000); assert.equal(jobReads, completedAt);
      pass(`uncertain retry (${outcome}) reconciles server state and polls pending/running to terminal once`);
    }
    for (const oldStatus of ['failed', 'cancelled']) {
      job = { ...baseline, status: oldStatus, progress: 0, can_retry: true, can_revise: true };
      retryOutcome = 'delayed';
      await page.goto(`${baseURL}/jobs/fixture-job`);
      await page.getByRole('button', { name: '重试任务', exact: true }).waitFor();
      const requestsBefore = retryRequests;
      const staleReadsBefore = staleRetryReads.length;
      await page.getByRole('button', { name: '重试任务', exact: true }).click();
      await page.getByText('研究记录已保存。', { exact: true }).waitFor({ timeout: 25000 });
      assert.deepEqual(staleRetryReads.slice(staleReadsBefore), Array.from({ length: 3 }, () => ({ status: oldStatus, execution_version: 0 })));
      assert.equal(retryRequests, requestsBefore + 1); assert.equal(job.execution_version, 1);
      assert.equal(await page.getByRole('main').getByRole('alert').count(), 0);
      pass(`retry response lost before commit keeps checking through repeated old ${oldStatus} state`);
    }
    job = { ...baseline, status: 'failed', progress: 0, can_retry: true, can_revise: true };
    retryOutcome = 'unconfirmed';
    await page.goto(`${baseURL}/jobs/fixture-job`); await page.getByRole('button', { name: '重试任务', exact: true }).click();
    const uncertainRequests = retryRequests;
    const resumeCheck = page.getByRole('button', { name: '继续核对重试结果', exact: true });
    await resumeCheck.waitFor({ timeout: 25000 });
    await page.getByText('重试结果仍未确认。请稍后继续核对，避免重复提交。', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '重试任务', exact: true }).isDisabled(), true);
    await fit('unconfirmed retry');
    await screenshot('retry-unconfirmed.png');
    const pausedAt = jobReads; await page.waitForTimeout(4000); assert.equal(jobReads, pausedAt);
    retryCommitAfterReads = 0;
    await resumeCheck.click();
    await page.getByText('研究记录已保存。', { exact: true }).waitFor({ timeout: 15000 });
    assert.equal(retryRequests, uncertainRequests); assert.equal(job.execution_version, 1);
    assert.equal(await page.getByRole('main').getByRole('alert').count(), 0);
    pass('retry reconciliation is bounded; manual recovery only reads and does not submit again');
    job = { ...baseline, status: 'failed', progress: 0, can_retry: true, can_revise: true };
    retryOutcome = 'blocked408';
    await page.goto(`${baseURL}/jobs/fixture-job`); await page.getByRole('button', { name: '重试任务', exact: true }).click();
    const blockedRequests = retryRequests;
    await resumeCheck.waitFor({ timeout: 25000 });
    assert.equal(await page.getByRole('button', { name: '重试任务', exact: true }).isDisabled(), true);
    const blockedAt = jobReads; await page.waitForTimeout(4000); assert.equal(jobReads, blockedAt);
    blockJobReads = false; retryCommitAfterReads = 0;
    await page.getByRole('button', { name: '重新连接', exact: true }).click();
    await page.getByText('研究记录已保存。', { exact: true }).waitFor({ timeout: 15000 });
    assert.equal(retryRequests, blockedRequests); assert.equal(job.execution_version, 1);
    assert.equal(await page.getByRole('main').getByRole('alert').count(), 0);
    pass('proxy 408 stays uncertain; failed and hung reads time out and reconnect only resumes reading');
    job = { ...baseline, status: 'failed', progress: 0, can_retry: true, can_revise: true };
    retryOutcome = 'rejected';
    await page.goto(`${baseURL}/jobs/fixture-job`); await page.getByRole('button', { name: '重试任务', exact: true }).click();
    await page.getByText('演示：这个任务已达到重试上限。', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '重试任务', exact: true }).isEnabled(), true);
    assert.equal(await resumeCheck.count(), 0);
    const rejectedAt = jobReads; await page.waitForTimeout(4000); assert.equal(jobReads, rejectedAt);
    pass('explicit retry rejection does not enter uncertain reconciliation');
    await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto(`${baseURL}/reports/fixture-report`); await page.getByRole('heading', { name: report.title }).first().waitFor();
    assert.equal(await page.locator('#report-claims').getAttribute('open'), null); assert.equal(await page.locator('#report-evidence').getAttribute('open'), null);
    await reducedTransparency(true); await page.getByRole('button', { name: '分享', exact: true }).click();
    const shareDialog = page.getByRole('dialog', { name: '创建只读分享链接' });
    await shareDialog.waitFor(); await checkMaterial(shareDialog, false);
    await page.keyboard.press('Escape'); await shareDialog.waitFor({ state: 'hidden' });
    assert.equal(await page.getByRole('button', { name: '分享', exact: true }).evaluate((element) => element === document.activeElement), true);
    await reducedTransparency(false);
    pass('reduced transparency uses solid navigation and unblurred public, workspace and modal scrims');
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
    for (const id of ['report-claims', 'report-evidence']) {
      await page.locator(`#${id} > summary`).focus(); await page.keyboard.press('Enter');
      assert.equal(await page.locator(`#${id}`).getAttribute('open'), null);
      await page.keyboard.press('Space'); assert.notEqual(await page.locator(`#${id}`).getAttribute('open'), null);
    }
    const reportTextSize = await page.locator('.report-prose > p').first().evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
    await page.setViewportSize({ width: 320, height: 740 });
    const reportRootFontSize = await page.locator('html').evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
    await page.evaluate(() => document.documentElement.style.fontSize = '200%');
    await page.waitForFunction((baseline) => parseFloat(getComputedStyle(document.documentElement).fontSize) >= baseline * 1.99, reportRootFontSize);
    await fit('expanded report with 200% text at 320px');
    const enlargedTextSize = await page.locator('.report-prose > p').first().evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
    assert.ok(enlargedTextSize >= reportTextSize * 1.8, `report text did not enlarge: ${reportTextSize} -> ${enlargedTextSize}`);
    await page.locator('#report-evidence > summary').focus();
    assert.equal(await page.locator('#report-evidence > summary').evaluate((element) => element.getBoundingClientRect().width <= innerWidth), true);
    await page.evaluate(() => document.documentElement.style.fontSize = '');
    await page.waitForFunction((baseline) => Math.abs(parseFloat(getComputedStyle(document.documentElement).fontSize) - baseline) < 0.01, reportRootFontSize);
    pass('report details support Enter and Space; actual report text enlarges without overflow at 320px');
    await page.setViewportSize({ width: 320, height: 740 }); await fit('report 320px'); pass('expanded report and evidence fit a 320px viewport');
    await page.locator('#report-claims > summary').click(); await page.locator('#report-evidence > summary').click();
    await page.setViewportSize({ width: 375, height: 812 }); await screenshot('report-mobile-light.png');
    await page.getByRole('button', { name: '切换到深色主题' }).click();
    await page.waitForFunction(() => document.documentElement.classList.contains('dark'));
    await page.emulateMedia({ media: 'print' });
    await page.waitForFunction(() => {
      const paper = getComputedStyle(document.documentElement);
      return matchMedia('print').matches && paper.backgroundColor === 'rgb(255, 255, 255)' && paper.colorScheme === 'light' && getComputedStyle(document.body).backgroundColor === 'rgb(255, 255, 255)';
    });
    assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor), 'rgb(255, 255, 255)');
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
