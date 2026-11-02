// Run only against an isolated test server: this script creates fixture reports.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const base = process.env.TEST_BASE_URL || 'http://127.0.0.1:8001';

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const fixture = await browser.newContext();
  const failures = [];
  async function write(path, data) {
    const response = await fixture.request.put(base + '/api' + path, { headers: { 'X-Work-Report': '1' }, data });
    assert.ok(response.ok(), await response.text());
    return response.json();
  }
  async function test(name, body) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, timezoneId: 'Asia/Shanghai' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.clock.setFixedTime(new Date('2026-10-20T12:00:00+08:00'));
    try {
      await page.goto(base + '/#daily');
      await page.locator('#today-display').filter({ hasText: '2026' }).waitFor();
      await body(page);
      assert.deepEqual(errors, []);
      console.log('PASS ' + name);
    } catch (error) {
      failures.push(name);
      console.error('FAIL ' + name + ': ' + error.message);
    } finally { await page.close(); }
  }
  async function blockedGeneration(page, body) {
    let release, started;
    const gate = new Promise(resolve => { release = resolve; });
    const seen = new Promise(resolve => { started = resolve; });
    await page.route('**/api/reports/daily/generate', async route => {
      started(); await gate;
      await route.fulfill({ json: { status: 'ok', items: [{ title: '当前日期生成结果', text: '回归测试', source_refs: ['input:work_content'] }], warnings: [] } });
    });
    await page.locator('#daily-generate').click();
    await seen;
    try { await body(); } finally { release(); }
  }
  try {
    await write('/profile', { name: '回归测试', role: '产品经理', dept: '' });
    const upload = await fixture.request.post(base + '/api/files?report_date=2026-10-20&filename=fixture.txt', {
      headers: { 'X-Work-Report': '1', 'Content-Type': 'application/octet-stream' }, data: Buffer.from('fixture')
    });
    assert.equal(upload.status(), 201);
    const file = await upload.json();
    await write('/reports/daily/2026-10-20', { notes: '本日工作输入', points: [{ title: '已保存日报' }], file_ids: [file.id] });
    await write('/reports/daily/2026-10-26', { notes: '其他日期输入', points: [{ title: '其他日期日报' }] });
    await write('/reports/weekly/2026-10-26', { notes: '跨月周报', points: [{ title: '跨月周报' }] });
    for (let i = 1; i <= 53; i++) {
      const day = new Date(Date.UTC(2026, 0, i)).toISOString().slice(0, 10);
      await write('/reports/daily/' + day, { points: [{ title: '历史记录' + i }] });
    }
    await test('generation cannot switch into a different report via history', async page => {
      await blockedGeneration(page, async () => {
        await page.locator('.menu-leaf[data-route="history"]').click();
        await page.locator('[data-open-record="daily:2026-10-26"]').click();
        assert.equal(await page.locator('#daily-value').textContent(), '2026 / 10 / 20');
      });
    });
    await test('generation locks attachment editing, upload and save', async page => {
      await blockedGeneration(page, async () => {
        assert.equal(await page.locator('#upload-drop').isDisabled(), true);
        assert.equal(await page.locator('[data-save-draft="daily"]').isDisabled(), true);
        assert.equal(await page.locator('[data-remove]').first().isDisabled(), true);
        assert.equal(await page.locator('#daily-notes').getAttribute('readonly') !== null, true);
      });
    });
    await test('historic cross-month week opens its owning month', async page => {
      await page.locator('.menu-leaf[data-route="history"]').click();
      await page.locator('[data-open-record="weekly:2026-10-26"]').click();
      await page.locator('#weekly-trigger').click();
      assert.equal(await page.locator('#calendar-title').textContent(), '2026年 11月');
      assert.equal(await page.locator('[data-week-anchor="2026-11-01"]').getAttribute('aria-selected'), 'true');
    });
    await test('pagination suppresses duplicate simultaneous requests', async page => {
      await page.locator('.menu-leaf[data-route="history"]').click();
      await page.locator('.history-card').nth(49).waitFor();
      await page.waitForFunction(()=>{const b=document.querySelector('#history-more');return !b.hidden&&!b.disabled;});
      let release, started, requests = 0;
      const gate = new Promise(resolve => { release = resolve; });
      const seen = new Promise(resolve => { started = resolve; });
      await page.route('**/api/reports?limit=50&offset=50*', async route => {
        requests++; started(); await gate; await route.continue();
      });
      await page.locator('#history-more').evaluate(button => { button.click(); button.click(); });
      await seen;
      release();
      await page.waitForFunction(() => document.querySelectorAll('.history-card').length === 56);
      assert.equal(requests, 1);
    });
    await test('period loading disables generation until correct inputs arrive', async page => {
      let release, started;
      const gate = new Promise(resolve => { release = resolve; });
      const seen = new Promise(resolve => { started = resolve; });
      await page.route('**/api/drafts/daily/2026-10-26', async route => { started(); await gate; await route.continue(); });
      await page.locator('#daily-trigger').click();
      await page.locator('[data-day="2026-10-26"]').click();
      await seen;
      try {
        assert.equal(await page.locator('#daily-generate').isDisabled(), true);
        assert.equal(await page.locator('#daily-notes').inputValue(), '');
      }
      finally { release(); }
      await page.waitForFunction(() => document.querySelector('#daily-notes').value === '其他日期输入');
      assert.equal(await page.locator('#daily-generate').isEnabled(), true);
    });
    await test('invalid API key is rejected locally and a valid token can be saved', async page => {
      let writes = 0;
      page.on('request', request => {
        if (request.url().endsWith('/api/model-settings') && request.method() === 'PUT') writes++;
      });
      await page.locator('#account-trigger').click();
      await page.locator('#account-dropdown [data-open-settings="api"]').click();
      for (const key of ['误填的密钥内容', 'sk-fixture other', '•'.repeat(40), '*'.repeat(40)]) {
        await page.locator('#model-api-key').fill(key);
        await page.locator('#save-settings').click();
        await page.locator('#model-api-key-error').filter({ hasText: '格式无效' }).waitFor();
        assert.equal(await page.locator('#model-api-key').getAttribute('aria-invalid'), 'true');
      }
      assert.equal(writes, 0);
      const before = await (await fixture.request.get(base + '/api/model-settings')).json();
      assert.equal(before.has_api_key, true);
      await page.locator('#model-api-key').fill('test-only-key');
      await page.locator('#save-settings').click();
      await page.locator('#settings-modal').waitFor({ state: 'hidden' });
      assert.equal(writes, 1);
      await page.locator('#account-trigger').click();
      await page.locator('#account-dropdown [data-open-settings="api"]').click();
      assert.equal(await page.locator('#model-api-key').inputValue(), '');
      assert.equal(await page.locator('#model-api-key-error').isHidden(), true);
    });
    assert.deepEqual(failures, [], 'Frontend regressions failed');
  } finally { await fixture.close(); await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
