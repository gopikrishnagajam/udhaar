// Actual app JavaScript in a browser; session APIs are simulated except the final check.
// No emails, provider accounts, or existing browser profiles are used.
const {chromium} = require('playwright-core');
const assert = require('node:assert/strict');
const base = process.env.UDHAAR_TEST_BASE_URL || 'http://127.0.0.1:8000';
const results = [];
let browser;

async function check(name, task) {
  try {
    await task();
    results.push({name, status: 'PASS'});
  } catch (error) {
    results.push({name, status: 'FAIL', detail: error.message});
  }
}

async function scenario(options, task) {
  const context = await browser.newContext();
  const state = {
    hasSession: true, valid: !options.expired, refreshes: 0, requests: [],
    refreshStatus: options.refreshStatus || 200, logout: false,
    rejectAfterRefresh: false, refreshHeaders: [],
  };
  const hostname = new URL(base).hostname;
  await context.addCookies([
    {name: 'udhaar_sb_access', value: 'synthetic-access', url: base, httpOnly: true, sameSite: 'Lax'},
    {name: 'udhaar_sb_refresh', value: 'synthetic-refresh', domain: hostname, path: '/api/auth', httpOnly: true, sameSite: 'Lax'},
  ]);
  await context.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    state.requests.push(path);
    let status = 200, data = {};
    if (path === '/api/csrf') data = {csrf: 'test-csrf'};
    else if (path === '/api/auth/config') data = {provider: 'supabase', configured: true, has_session: state.hasSession};
    else if (path === '/api/me' || path.startsWith('/api/records')) {
      if (state.valid && !state.logout) {
        data = path === '/api/me' ? {id: 'test-user', name: 'Session Test', email: 'test@example.com'} : [];
      } else {
        status = 401;
        data = {detail: 'Session invalid or expired; please sign in again'};
      }
    } else if (path === '/api/auth/refresh') {
      state.refreshes++;
      state.refreshHeaders.push(request.headers());
      await new Promise(resolve => setTimeout(resolve, 80));
      status = state.refreshStatus;
      if (status === 200) {
        state.valid = !state.rejectAfterRefresh;
        data = {ok: true};
      } else {
        data = {detail: status === 429 ? 'Supabase authentication limit reached' : status === 503 ? 'Authentication service unavailable' : 'Please sign in again'};
      }
    } else if (path === '/api/auth/logout') {
      state.valid = false;
      state.hasSession = false;
      state.logout = true;
      data = {ok: true, provider_session_revoked: true};
    } else {
      await route.abort();
      return;
    }
    await route.fulfill({status, contentType: 'application/json', body: JSON.stringify(data), headers: status === 429 ? {'Retry-After': '120'} : {}});
  });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  try {
    await page.goto(base);
    await task(page, state, context);
  } finally {
    await context.close();
  }
}

(async () => {
  const executablePath = process.env.UDHAAR_TEST_BROWSER_PATH;
  browser = await chromium.launch({headless: true, ...(executablePath ? {executablePath} : {channel: process.env.UDHAAR_TEST_BROWSER_CHANNEL || 'msedge'})});
  try {
    await check('Expired access refreshes and restores dashboard', () => scenario({expired: true}, async (page, state) => {
      await page.locator('#logout').waitFor();
      assert.equal(state.refreshes, 1);
      assert.equal(state.requests.filter(path => path === '/api/me').length, 2);
      assert.equal(state.refreshHeaders[0]['x-csrf-token'], 'test-csrf');
    }));
    await check('Reload retains a valid session without refresh', () => scenario({}, async (page, state) => {
      await page.locator('#logout').waitFor();
      await page.reload();
      await page.locator('#logout').waitFor();
      assert.equal(state.refreshes, 0);
    }));
    await check('Parallel requests within one tab share a refresh', () => scenario({}, async (page, state) => {
      await page.locator('#logout').waitFor();
      state.valid = false;
      const values = await page.evaluate(() => Promise.all([api('/api/records'), api('/api/records'), api('/api/me')]));
      assert.equal(values.length, 3);
      assert.equal(state.refreshes, 1);
    }));
    await check('Rejected refresh at startup shows sign in without looping', () => scenario({expired: true, refreshStatus: 401}, async (page, state) => {
      await page.locator('#otp-form').waitFor();
      assert.equal(state.refreshes, 1);
      assert.match(await page.locator('#otp-error').textContent(), /session expired/i);
    }));
    await check('Startup outage explains failure and retry restores the session', () => scenario({expired: true, refreshStatus: 503}, async (page, state) => {
      await page.locator('#retry-session').waitFor();
      assert.match(await page.locator('#otp-error').textContent(), /service unavailable/i);
      assert.equal(state.logout, false);
      state.refreshStatus = 200;
      await page.locator('#retry-session').click();
      await page.locator('#logout').waitFor();
      assert.equal(state.refreshes, 2);
    }));
    await check('API refresh outage keeps status and does not loop', () => scenario({}, async (page, state) => {
      await page.locator('#logout').waitFor();
      state.valid = false;
      state.refreshStatus = 503;
      const error = await page.evaluate(() => api('/api/records').catch(error => ({message: error.message, status: error.status})));
      assert.match(error.message, /service unavailable/i);
      assert.equal(error.status, 503);
      assert.equal(state.refreshes, 1);
      assert.equal(await page.locator('#logout').count(), 1);
    }));
    await check('Refresh rate limit retains status, wait, and explanation', () => scenario({}, async (page, state) => {
      await page.locator('#logout').waitFor();
      state.valid = false;
      state.refreshStatus = 429;
      const error = await page.evaluate(() => api('/api/records').catch(error => ({message: error.message, status: error.status, retry: error.retryAfter})));
      assert.equal(error.status, 429);
      assert.equal(error.retry, 120);
      assert.match(error.message, /120 seconds/);
    }));
    await check('Startup rate limit disables session retry until countdown ends', () => scenario({expired: true, refreshStatus: 429}, async (page, state) => {
      await page.clock.install();
      await page.locator('#retry-session').waitFor();
      assert.equal(await page.locator('#retry-session').isDisabled(), true);
      assert.match(await page.locator('#retry-session').textContent(), /Retry session in/);
      await page.clock.fastForward(121000);
      assert.equal(await page.locator('#retry-session').isDisabled(), false);
      assert.equal(state.refreshes, 1);
    }));
    await check('Permanent session expiry clears dashboard, records, and dialogs', () => scenario({}, async (page, state) => {
      await page.locator('#logout').waitFor();
      await page.locator('#new-record').click();
      state.valid = false;
      state.refreshStatus = 401;
      await page.evaluate(() => api('/api/records').catch(() => {}));
      assert.equal(await page.locator('#otp-form').count(), 1);
      assert.equal(await page.locator('#logout, .modal-backdrop').count(), 0);
      assert.deepEqual(await page.evaluate(() => ({user, records, activeRecord, shareLink})), {user: null, records: [], activeRecord: null, shareLink: ''});
      assert.match(await page.locator('#otp-error').textContent(), /session expired/i);
    }));
    await check('401 after a successful refresh ends session without another refresh', () => scenario({}, async (page, state) => {
      await page.locator('#logout').waitFor();
      state.valid = false;
      state.rejectAfterRefresh = true;
      await page.evaluate(() => api('/api/records').catch(() => {}));
      assert.equal(state.refreshes, 1);
      assert.equal(await page.locator('#otp-form').count(), 1);
    }));
    await check('Parallel failed refreshes share one parsed rate-limit result', () => scenario({}, async (page, state) => {
      await page.locator('#logout').waitFor();
      state.valid = false;
      state.refreshStatus = 429;
      const errors = await page.evaluate(() => Promise.all(['/api/me', '/api/records'].map(path => api(path).catch(error => ({status: error.status, retry: error.retryAfter})))));
      assert.deepEqual(errors, [{status: 429, retry: 120}, {status: 429, retry: 120}]);
      assert.equal(state.refreshes, 1);
    }));
    await check('Logout stays signed out after reload', () => scenario({}, async (page, state) => {
      await page.locator('#logout').click();
      await page.locator('#otp-form').waitFor();
      await page.reload();
      await page.locator('#otp-form').waitFor();
      assert.equal(state.requests.filter(path => path === '/api/auth/logout').length, 1);
    }));
    await check('Authentication cookies are unreadable by JavaScript', () => scenario({}, async (page, state, context) => {
      await page.locator('#logout').waitFor();
      assert.doesNotMatch(await page.evaluate(() => document.cookie), /udhaar_sb_access|udhaar_sb_refresh/);
      assert.ok((await context.cookies()).filter(cookie => cookie.name.startsWith('udhaar_sb_')).every(cookie => cookie.httpOnly));
    }));
    await check('Session tokens are absent from web storage', () => scenario({}, async page => {
      await page.locator('#logout').waitFor();
      const storage = await page.evaluate(() => JSON.stringify({local: {...localStorage}, session: {...sessionStorage}}));
      assert.doesNotMatch(storage, /synthetic-access|synthetic-refresh/);
    }));
    await check('Observation: separate tabs still refresh independently', () => scenario({}, async (page, state, context) => {
      await page.locator('#logout').waitFor();
      const second = await context.newPage();
      await second.goto(base);
      await second.locator('#logout').waitFor();
      state.valid = false;
      await Promise.all([page.evaluate(() => api('/api/records')), second.evaluate(() => api('/api/records'))]);
      assert.equal(state.refreshes, 2);
    }));
    await check('Live server rejects anonymous access and missing CSRF', async () => {
      const context = await browser.newContext();
      try {
        const page = await context.newPage();
        await page.goto(base);
        await page.locator('#otp-form').waitFor();
        const result = await page.evaluate(async () => {
          const csrf = (await (await fetch('/api/csrf')).json()).csrf;
          const missing = await fetch('/api/auth/refresh', {method: 'POST'});
          const anonymous = await fetch('/api/auth/refresh', {method: 'POST', headers: {'X-CSRF-Token': csrf}});
          const me = await fetch('/api/me');
          const logout = await fetch('/api/auth/logout', {method: 'POST', headers: {'X-CSRF-Token': csrf}});
          return {missing: missing.status, anonymous: anonymous.status, me: me.status, logout: logout.status, body: await logout.json()};
        });
        assert.deepEqual(result, {missing: 403, anonymous: 401, me: 401, logout: 200, body: {ok: true, provider_session_revoked: false}});
      } finally {
        await context.close();
      }
    });
    console.log(JSON.stringify({environment: 'Actual app JavaScript; simulated session API except final live-server check; no email sent', results, passed: results.filter(result => result.status === 'PASS').length, failed: results.filter(result => result.status === 'FAIL').length}, null, 2));
    if (results.some(result => result.status === 'FAIL')) process.exitCode = 1;
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
