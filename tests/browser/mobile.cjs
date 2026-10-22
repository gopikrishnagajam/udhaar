// Responsive UI checks against a disposable database; never sends real email.
const {chromium} = require('playwright-core');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs/promises');
const port = Number(process.env.UDHAAR_TEST_PORT || 8013), base = `http://127.0.0.1:${port}`;
const python = process.env.UDHAAR_TEST_PYTHON || path.resolve(__dirname, '../../.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const server = spawn(python, [path.join(__dirname, 'invitation_server.py')], {
  windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], env: {...process.env, UDHAAR_TEST_PORT: String(port)},
});
let logs = '', browser;
server.stdout.on('data', data => logs += data);
server.stderr.on('data', data => logs += data);
const results = [], errors = [];
const sizes = [
  {width:320,height:568}, {width:390,height:844}, {width:600,height:800},
  {width:768,height:1024}, {width:820,height:1180}, {width:1024,height:768},
  {width:1440,height:900}, {width:667,height:375}, {width:844,height:390}, {width:375,height:667},
];

async function fits(page, label) {
  const overflow = await page.evaluate(() => {
    const scope = document.querySelector('.modal-content') || document.querySelector('main') || document.querySelector('#app');
    const invalid = [...scope.querySelectorAll('*')].filter(el => {
      const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
      let left = rect.left, right = rect.right;
      // Text deliberately ellipsized on desktop is clipped by its parent.
      for (let parent = el.parentElement; parent && parent !== scope; parent = parent.parentElement) {
        if (getComputedStyle(parent).overflowX !== 'visible') {
          const clip = parent.getBoundingClientRect();
          left = Math.max(left, clip.left);right = Math.min(right, clip.right);
        }
      }
      return rect.width && rect.height && style.position !== 'absolute' && (left < -1 || right > innerWidth + 1);
    }).map(el => `${el.tagName}.${el.className}`);
    return {document: document.documentElement.scrollWidth > innerWidth + 1, content: scope.scrollWidth > scope.clientWidth + 1, invalid};
  });
  assert.deepEqual(overflow, {document:false, content:false, invalid:[]}, label);
}
async function dialogFits(page) {
  await page.getByRole('dialog').waitFor();
  await fits(page, 'Dialog content fits the viewport');
  const rect = await page.locator('.modal').boundingBox(), viewport = page.viewportSize();
  assert.ok(rect.y >= -1 && rect.y + rect.height <= viewport.height + 1, 'Dialog fits screen height');
  if (viewport.width <= 600) {
    assert.ok(Math.abs(rect.width - viewport.width) <= 1 && Math.abs(rect.height - viewport.height) <= 1, 'Phone dialog fills the screen');
  }
  const close = await page.locator('.close-modal').boundingBox();
  assert.ok(close.width >= 44 && close.height >= 44, 'Close control is touch sized');
}
async function closeDialog(page) {
  await page.getByRole('button', {name:'Close', exact:true}).click();
  await page.getByRole('dialog').waitFor({state:'detached'});
  assert.equal(await page.locator('#app').evaluate(el => el.inert), false);
  assert.notEqual(await page.locator('body').evaluate(el => el.style.position), 'fixed');
}
async function navigate(page, tab) {
  if (page.viewportSize().width <= 900) await page.locator('#toggle-nav').click();
  await page.locator(`[data-tab=${tab}]`).click();
}

(async () => {
  let ready = false;
  for (let n=0; n<100; n++) {
    if (server.exitCode !== null) throw new Error(logs || 'Test server stopped');
    try { if ((await fetch(base + '/api/health')).ok) { ready = true; break; } } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(ready, `Test server did not start: ${logs}`);
  const executablePath = process.env.UDHAAR_TEST_BROWSER_PATH;
  browser = await chromium.launch({headless:true, ...(executablePath ? {executablePath} : {channel:process.env.UDHAAR_TEST_BROWSER_CHANNEL || 'msedge'})});
  const context = await browser.newContext({viewport:sizes[1], isMobile:true, hasTouch:true});
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base);
  await page.locator('#auth-form').waitFor();
  for (const size of sizes) {
    await page.setViewportSize(size);
    await fits(page, `Sign in at ${size.width}x${size.height}`);
  }
  await page.setViewportSize(sizes[1]);
  await page.evaluate(async () => {
    await send('/api/register', {name:'Mobile Tester', email:'mobile@example.com', password:'StrongPass123!'});
  });
  await page.reload();
  await page.locator('#new-record').waitFor();
  results.push('Sign in fits phone, tablet, desktop and landscape widths');

  // Create a real shared record with deliberately long content.
  await page.locator('#new-record').click();
  await dialogFits(page);
  await page.locator('[name=item_name]').fill('Mobile lending record with a very long item name ' + 'X'.repeat(90));
  await page.locator('[name=contact_name]').fill('Recipient with a long display name ' + 'Y'.repeat(50));
  await page.locator('[name=quantity]').fill('3');
  await page.locator('[name=notes]').fill(('A long private note ' + 'Z'.repeat(100) + '\n').repeat(10));
  await page.locator('label.mode-option').nth(1).click();
  await page.locator('[name=contact_email]').fill('recipient-with-a-long-address@example.com');
  await fits(page, 'New record with shared email');
  await page.locator('#record-form button[type=submit]').click();
  await page.locator('#share-action').waitFor();
  await dialogFits(page);
  await closeDialog(page);
  results.push('Phone form scrolls to every field and saves a shared record');

  for (const size of sizes) {
    await page.setViewportSize(size);
    await fits(page, `Dashboard at ${size.width}x${size.height}`);
    await page.locator('[data-rec]').click();
    await dialogFits(page);
    // Scroll the long details without losing the close button.
    await page.locator('.modal-content').evaluate(el => el.scrollTop = el.scrollHeight);
    const close = await page.locator('.close-modal').boundingBox();
    assert.ok(close.y >= 0 && close.y + close.height <= size.height, 'Close remains visible after scrolling');
    await closeDialog(page);
    await page.locator('#new-record').click();
    await dialogFits(page);
    await closeDialog(page);
  }
  results.push('Dashboard, record details and new-record form fit ten screen sizes');

  await page.setViewportSize(sizes[1]);
  await page.locator('#toggle-nav').click();
  assert.equal(await page.locator('#toggle-nav').getAttribute('aria-expanded'), 'true');
  assert.equal(await page.locator('.main').evaluate(el => el.inert), true);
  await page.keyboard.press('Shift+Tab');
  assert.equal(await page.locator('#logout').evaluate(el => el === document.activeElement), true, 'Drawer traps focus');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#toggle-nav').getAttribute('aria-expanded'), 'false');
  assert.equal(await page.locator('#sidebar').evaluate(el => el.inert), true);
  await page.locator('#toggle-nav').click();
  await page.locator('.navigation-backdrop').click({position:{x:385,y:150}});
  assert.equal(await page.locator('#toggle-nav').getAttribute('aria-expanded'), 'false');
  await navigate(page, 'ON');
  await fits(page, 'Shared records tab');
  await page.locator('#toggle-nav').click();
  await page.setViewportSize({width:1024,height:768});
  assert.equal(await page.locator('#sidebar').evaluate(el => el.inert), false);
  assert.equal(await page.locator('.main').evaluate(el => el.inert), false);
  results.push('Navigation closes with Escape, outside tap, tab selection and desktop resize');

  await page.setViewportSize(sizes[1]);
  await page.locator('#new-record').click();
  await page.locator('[name=item_name]').fill('Private book');
  await page.locator('[name=contact_name]').fill('A friend');
  await page.locator('#record-form button[type=submit]').click();
  await page.locator('#edit-action').click();
  await dialogFits(page);
  await page.locator('[name=notes]').fill('Updated on a phone');
  await page.locator('#edit-form button[type=submit]').click();
  await page.locator('#return-action').click();
  await dialogFits(page);
  await page.locator('#return-form button[type=submit]').click();
  await page.locator('.detail-summary strong').nth(1).filter({hasText:/^0$/}).waitFor();
  await closeDialog(page);
  await page.locator('#toggle-nav').click();
  await page.locator('#invite-friends').click();
  await dialogFits(page);
  await page.locator('#app-invite-form input').fill('friend@example.com');
  await page.locator('#app-invite-form button[type=submit]').click();
  await page.getByText('friend@example.com', {exact:true}).waitFor();
  await closeDialog(page);
  results.push('Editing, returns and friend invitations work through phone dialogs');

  await page.locator('[data-rec]').filter({hasText:'Mobile lending record'}).click();
  await page.locator('#share-action').click();
  await dialogFits(page);
  await closeDialog(page);
  await navigate(page, 'ALL');
  await page.locator('#new-record').click();
  await page.locator('[name=item_name]').fill('Focus test');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.modal-backdrop').count(), 0, 'Escape works after typing');
  assert.equal(await page.locator('#new-record').evaluate(el => el === document.activeElement), true, 'Focus returns to opener');
  await page.locator('#new-record').click();
  await page.locator('[name=notes]').fill('Keyboard viewport check');
  await page.setViewportSize({width:390,height:360});
  await dialogFits(page);
  const focused = await page.locator('[name=notes]').boundingBox();
  assert.ok(focused.y >= 60 && focused.y + focused.height <= 360, 'Focused field stays in the reduced viewport');
  await page.setViewportSize(sizes[1]);
  await page.locator('#record-form button[type=submit]').focus();
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('.close-modal').evaluate(el => el === document.activeElement), true, 'Dialog traps focus');
  await closeDialog(page);
  await page.evaluate(() => window.scrollTo(0, 200));
  const scrollY = await page.evaluate(() => window.scrollY);
  await page.evaluate(() => openNew());
  await closeDialog(page);
  assert.equal(await page.evaluate(() => window.scrollY), scrollY, 'Closing preserves page position');
  results.push('Dialogs trap and restore focus, preserve scrolling and close after typing');

  const emails = await (await fetch(base + '/__test/emails')).json();
  const message = emails.find(email => email.email === 'recipient-with-a-long-address@example.com');
  const url = message.message.match(/http:\/\/127\.0\.0\.1:\d+\/share\/\S+/)[0];
  assert.equal(new URL(url).origin, base);
  const guest = await context.newPage();
  guest.on('pageerror', error => errors.push(error.message));
  await guest.goto(url);
  await guest.locator('#accept-invite').waitFor();
  await fits(guest, 'Guest acknowledgment with long content');
  await guest.locator('#accept-invite').click();
  await guest.locator('#guest-return').click();
  await dialogFits(guest);
  await guest.locator('#guest-return-form button[type=submit]').click();
  await guest.locator('.modal-backdrop').waitFor({state:'detached'});
  await fits(guest, 'Guest return');
  results.push('Guest acknowledgments and return dialogs work on phones');

  const recipientContext = await browser.newContext({viewport:sizes[1],isMobile:true,hasTouch:true});
  const recipient = await recipientContext.newPage();
  recipient.on('pageerror', error => errors.push(error.message));
  await recipient.goto(base);
  await recipient.locator('#auth-form').waitFor();
  await recipient.evaluate(() => send('/api/register', {name:'Inbox recipient',email:'mobile-inbox@example.com',password:'StrongPass123!'}));
  await recipient.reload();
  await recipient.locator('#new-record').waitFor();
  await page.locator('#new-record').click();
  await page.locator('[name=item_name]').fill('Mobile inbox loan');
  await page.locator('[name=contact_name]').fill('Inbox recipient');
  await page.locator('label.mode-option').nth(1).click();
  await page.locator('[name=contact_email]').fill('mobile-inbox@example.com');
  await page.locator('#record-form button[type=submit]').click();
  await page.locator('#share-action').waitFor();
  await closeDialog(page);
  await recipient.reload();
  await navigate(recipient, 'INBOX');
  await fits(recipient, 'Mobile acknowledgment inbox');
  await recipient.locator('[data-invitation]').click();
  await dialogFits(recipient);
  await recipient.locator('#inbox-accept').click();
  await recipient.locator('#inbox-return').click();
  await dialogFits(recipient);
  await recipient.locator('#return-form button[type=submit]').click();
  await recipient.locator('#inbox-error').waitFor();
  await closeDialog(recipient);
  await page.reload();
  await page.locator('[data-rec]').filter({hasText:'Mobile inbox loan'}).click();
  await page.locator('.confirm-return').click();
  await page.getByText('All returned / completed', {exact:true}).waitFor();
  await closeDialog(page);
  await recipientContext.close();
  results.push('Phone inbox supports handover acknowledgment and lender-confirmed returns');

  // Test the hosted email-code layout without contacting an auth provider.
  const otp = await context.newPage();
  await otp.route('**/api/auth/config', route => route.fulfill({json:{provider:'supabase',configured:true,has_session:false}}));
  await otp.route('**/api/auth/otp', route => route.fulfill({json:{retry_after_seconds:60}}));
  await otp.goto(base);
  await otp.locator('#otp-form input[name=email]').fill('long-email-address-for-mobile@example.com');
  await otp.locator('#otp-form button[type=submit]').click();
  await otp.locator('[name=code]').waitFor();
  await fits(otp, 'Email code sign in');
  assert.ok(await otp.locator('[name=code]').evaluate(el => parseFloat(getComputedStyle(el).fontSize) >= 16), 'Mobile fields avoid focus zoom');
  results.push('Hosted email-code sign in fits mobile screens');

  // Exercise unknown-email recovery and signup with the actual app JavaScript.
  const authRequests = [];
  await otp.route('**/api/auth/otp', route => {
    const payload = route.request().postDataJSON();
    authRequests.push(payload);
    if (payload.email === 'new@example.com' && !payload.signup) {
      return route.fulfill({status:409,json:{detail:{code:'signup_required',message:'Create your Udhaar account to continue with this email.'}}});
    }
    if (payload.email === 'existing@example.com' && payload.signup) {
      return route.fulfill({status:409,json:{detail:'An account with this email already exists. Sign in instead'}});
    }
    if (payload.email === 'offline@example.com') {
      return route.fulfill({status:503,json:{detail:'Authentication service unavailable; please retry'}});
    }
    return route.fulfill({json:{retry_after_seconds:60}});
  });
  await otp.route('**/api/auth/verify', route => route.fulfill({json:{id:'new-user',name:'New user',email:'new@example.com'}}));
  await otp.route('**/api/records', route => route.fulfill({json:[]}));
  await otp.route('**/api/inbox', route => route.fulfill({json:[]}));
  await otp.goto(base);
  await otp.locator('[name=email]').fill('NEW@example.com');
  await otp.locator('#otp-form button[type=submit]').click();
  await otp.locator('[name=name]').waitFor();
  assert.equal(new URL(otp.url()).pathname, '/signup');
  assert.equal(await otp.locator('[name=email]').inputValue(), 'new@example.com');
  assert.match(await otp.locator('#otp-error').innerText(), /Create your Udhaar account/);
  assert.equal(await otp.locator('[name=code]').count(), 0);
  assert.equal(await otp.locator('#otp-form button[type=submit]').isEnabled(), true);
  await fits(otp, 'Unknown-email signup guidance');
  await otp.locator('[name=name]').fill('New user');
  await otp.locator('#otp-form button[type=submit]').click();
  await otp.locator('[name=code]').fill('123456');
  await otp.locator('#otp-form button[type=submit]').click();
  await otp.locator('#new-record').waitFor();
  assert.deepEqual(authRequests.slice(0,2), [{email:'new@example.com',signup:false},{email:'new@example.com',signup:true}]);
  results.push('Unknown email opens signup with retained email, no cooldown, and completes verification');

  await otp.goto(base + '/signup');
  await otp.locator('[name=name]').fill('Existing user');
  await otp.locator('[name=email]').fill('existing@example.com');
  await otp.locator('#otp-form button[type=submit]').click();
  await otp.getByText('An account with this email already exists. Sign in instead', {exact:true}).waitFor();
  await otp.locator('#switch-auth').click();
  assert.equal(new URL(otp.url()).pathname, '/');
  assert.equal(await otp.locator('[name=email]').inputValue(), 'existing@example.com');
  await otp.locator('#otp-form button[type=submit]').click();
  await otp.locator('[name=code]').waitFor();
  assert.deepEqual(authRequests.at(-1), {email:'existing@example.com',signup:false});
  results.push('Duplicate signup retains email when switching to working sign-in');

  await otp.goto(base);
  await otp.locator('[name=email]').fill('offline@example.com');
  await otp.locator('#otp-form button[type=submit]').click();
  await otp.getByText('Authentication service unavailable; please retry', {exact:true}).waitFor();
  assert.equal(new URL(otp.url()).pathname, '/');
  assert.equal(await otp.locator('[name=name]').count(), 0);
  results.push('Provider errors keep users on sign-in and show the actual error');

  const screenshots = process.env.UDHAAR_TEST_SCREENSHOTS;
  if (screenshots) {
    await fs.mkdir(screenshots, {recursive:true});
    await page.screenshot({path:path.join(screenshots, 'mobile-dashboard.png'),fullPage:true});
    await page.locator('#new-record').click();
    await page.screenshot({path:path.join(screenshots, 'mobile-form.png')});
    await closeDialog(page);
  }
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({passed:results.length,results}, null, 2));
})().catch(error => {console.error(error);console.error(logs);process.exitCode=1;}).finally(async () => {
  if(browser)await browser.close();server.kill();
});
