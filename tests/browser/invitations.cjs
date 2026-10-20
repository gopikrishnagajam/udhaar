// Actual browser, UI, API and disposable database; email transport is simulated.
const {chromium} = require('playwright-core');
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const path = require('node:path');
const base = 'http://127.0.0.1:8012';
const python = process.env.UDHAAR_TEST_PYTHON || path.resolve(__dirname, '../../.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const server = spawn(python, [path.join(__dirname, 'invitation_server.py')], {windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']});
let logs = '', browser;
server.stdout.on('data', data => logs += data);
server.stderr.on('data', data => logs += data);
const results = [];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function register(page, name, email) {
  await page.goto(base);
  await page.locator('#auth-form').waitFor();
  await page.evaluate(async ({name, email}) => {
    await send('/api/register', {name, email, password: 'StrongPass123!'});
  }, {name, email});
  await page.reload();
  await page.locator('#new-record').waitFor();
}
async function createLoan(page, name, email, on=true) {
  await page.locator('#new-record').click();
  await page.locator('[name=item_name]').fill('Browser test book');
  await page.locator('[name=contact_name]').fill(name);
  if (on) {
    await page.locator('label.mode-option').nth(1).click();
    await page.locator('[name=contact_email]').fill(email);
  }
  await page.locator('#record-form button[type=submit]').click();
  await page.locator('#share-action').waitFor();
}

(async () => {
  for (let n=0; n<100; n++) {
    if (server.exitCode !== null) throw new Error(logs || 'Test server stopped');
    try { if ((await fetch(base + '/api/health')).ok) break; } catch {}
    await sleep(100);
  }
  const executablePath = process.env.UDHAAR_TEST_BROWSER_PATH;
  browser = await chromium.launch({headless: true, ...(executablePath ? {executablePath} : {channel: process.env.UDHAAR_TEST_BROWSER_CHANNEL || 'msedge'})});
  const ownerContext = await browser.newContext();
  const recipientContext = await browser.newContext();
  const guestContext = await browser.newContext();
  const owner = await ownerContext.newPage(), recipient = await recipientContext.newPage(), guest = await guestContext.newPage();
  const errors = [];
  for (const page of [owner, recipient, guest]) {page.setDefaultTimeout(10000);page.on('pageerror', error => errors.push(error.message));}
  await register(recipient, 'Recipient', 'recipient@example.com');
  await register(owner, 'Owner', 'owner@example.com');
  await createLoan(owner, 'Recipient', 'recipient@example.com');
  await owner.locator('.close-modal').click();
  await recipient.reload();
  await recipient.locator('[data-tab=INBOX]').click();
  await recipient.locator('[data-invitation]').click();
  await recipient.locator('#inbox-accept').click();
  await recipient.locator('#inbox-return').waitFor();
  await recipient.locator('#inbox-return').click();
  await recipient.locator('#return-form button[type=submit]').click();
  await recipient.locator('.close-modal').waitFor();
  await owner.reload();
  await owner.locator('[data-rec]').click();
  await owner.locator('.confirm-return').click();
  await owner.getByText('All returned / completed', {exact:true}).waitFor();
  await owner.locator('.close-modal').click();
  results.push('Registered recipient acknowledges and completes returns in app');

  await owner.locator('#invite-friends').click();
  for (const email of ['friend1@example.com', 'friend2@example.com']) {
    await owner.locator('#app-invite-form input').fill(email);
    await owner.locator('#app-invite-form button').click();
    await owner.getByText(email, {exact:true}).waitFor();
  }
  assert.equal(await owner.locator('#app-invite-form button').isDisabled(), true);
  await owner.locator('.close-modal').click();
  results.push('Invite dialog accepts email and disables new invites after two');

  await createLoan(owner, 'Guest', 'guest@example.com', false);
  await owner.locator('#share-action').click();
  await owner.locator('#share-form input').fill('guest@example.com');
  await owner.locator('#share-form button[type=submit]').click();
  await owner.locator('#share-action').waitFor();
  const emails = await (await fetch(base + '/__test/emails')).json();
  const message = emails.findLast(email => email.email === 'guest@example.com');
  assert.ok(message);
  assert.match(message.message, /Optional/);
  const url = message.message.match(/http:\/\/127\.0\.0\.1:8012\/share\/\S+/)[0];
  await guest.goto(url);
  await guest.locator('#accept-invite').click();
  await guest.locator('#guest-return').waitFor();
  assert.equal(await guest.locator('a[href="/signup"]').count(), 1);
  await guest.locator('#guest-return').click();
  await guest.locator('#guest-return-form button[type=submit]').click();
  await owner.locator('.close-modal').click();
  await owner.reload();
  await owner.locator('[data-rec]').first().click();
  await owner.locator('.confirm-return').click();
  await owner.getByText('All returned / completed', {exact:true}).waitFor();
  results.push('Private loan converts to email acknowledgment after daily invite cap; anonymous recipient completes it');

  await guest.setViewportSize({width:390, height:844});
  await guest.reload();
  assert.equal(await guest.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  assert.deepEqual(errors, []);
  results.push('Guest screen fits mobile width; no JavaScript errors');
  for (const [route, heading] of [['privacy', 'Privacy notice'], ['terms', 'Terms of use'], ['rights', 'Rights and licensing']]) {
    await guest.goto(`${base}/${route}`);
    await guest.getByRole('heading', {name:heading, exact:true}).waitFor();
    assert.equal(await guest.locator('.policy-header [aria-current=page]').count(), 1);
    assert.equal(await guest.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.match(await guest.locator('.site-footer').textContent(), /Gopi krishna Gajam/);
  }
  await guest.locator('.policy-header a[href="/"]').first().click();
  await guest.locator('#auth-form').waitFor();
  assert.equal(await guest.locator('.site-footer nav a').count(), 3);
  assert.deepEqual(errors, []);
  results.push('Public privacy, terms and MIT rights pages work on mobile and link back to sign in');
  console.log(JSON.stringify({passed:results.length, results}, null, 2));
})().catch(error => {console.error(error); console.error(logs); process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();server.kill();});
