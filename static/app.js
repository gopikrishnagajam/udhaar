/* Udhaar MVP — no frontend build tool needed. All server access is via same-origin JSON APIs. */
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const esc = (value = '') => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const prettyDate = (date) => date ? new Date(`${date}T12:00:00`).toLocaleDateString(undefined, {month:'short',day:'numeric',year:'numeric'}) : 'No return date';
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
let csrf = '', user = null, records = [], tab = 'ALL', activeRecord = null, newOpen = false, signup = window.location.pathname.replace(/\/$/, '') === '/signup', shareLink = '', notice = '', busy = false;
let authConfig = {provider:'local', configured:true}, authEmail = '', authName = '', otpSent = false, refreshPromise = null;
const otpCooldowns = new Map();
let authSubmitting = false;
let verifyRetryUntil = 0;

function updateOtpControls() {
 const form=$('#otp-form');if(!form)return;
 const email=(otpSent?authEmail:($('input[name=email]',form)?.value||'')).trim().toLowerCase();
 const remaining=Math.max(0,Math.ceil(((otpCooldowns.get(email)||0)-Date.now())/1000));
 const verifyRemaining=Math.max(0,Math.ceil((verifyRetryUntil-Date.now())/1000));
 const submit=$('button[type=submit]',form);
 submit.disabled=!authConfig.configured||authSubmitting||(otpSent?verifyRemaining>0:remaining>0);
 submit.textContent=otpSent?(verifyRemaining?`Verify in ${verifyRemaining}s`:'Verify and continue'):remaining?`Send code in ${remaining}s`:'Send sign-in code';
 const resend=$('#resend-code');if(resend){resend.disabled=authSubmitting||remaining>0;resend.textContent=remaining?`Resend in ${remaining}s`:'Resend code';}
}

async function requestOtpCode() {
 try {
  const result=await send('/api/auth/otp',{email:authEmail,signup});
  otpCooldowns.set(authEmail.toLowerCase(),Date.now()+(result.retry_after_seconds||60)*1000);
  return result;
 } catch(err) {
  if(err.status!==409) otpCooldowns.set(authEmail.toLowerCase(),Date.now()+(err.retryAfter||60)*1000);
  throw err;
 }
}

async function readApiResponse(resp) {
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const details = Array.isArray(body.detail) ? body.detail.map(d=>d.msg).join('; ') : body.detail;
    const error=new Error(typeof details === 'string' ? details : `Request failed (${resp.status})`);
    error.status=resp.status;
    error.retryAfter=Number(resp.headers.get('Retry-After'))||0;
    throw error;
  }
  return body;
}
function clearSignedInState() {
  authConfig.has_session=false;user=null;records=[];activeRecord=null;shareLink='';tab='ALL';otpSent=false;authName='';notice='';
  $$('.modal-backdrop, .toast').forEach(el=>el.remove());
}
function sessionExpired() {
  clearSignedInState();
  authScreen('Your session expired. Please sign in again.');
}
async function api(path, options = {}, retried = false) {
  const resp = await fetch(path, {credentials:'same-origin', ...options, headers: {...(options.body ? {'Content-Type':'application/json'} : {}), ...(options.method && options.method !== 'GET' ? {'X-CSRF-Token':csrf} : {}), ...(options.headers || {})}});
  const protectedRequest=path==='/api/me'||path==='/api/records'||path.startsWith('/api/records/');
  if(resp.status===401 && authConfig.provider==='supabase' && protectedRequest) {
    if(!retried && authConfig.has_session) {
      // Share the parsed result too: a Response body can only be consumed once.
      if(!refreshPromise) refreshPromise=fetch('/api/auth/refresh',{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':csrf}}).then(readApiResponse).finally(()=>{refreshPromise=null});
      try {await refreshPromise;}
      catch(error) {
        if(error.status===401) sessionExpired();
        if(error.status>=500) error.message='Sign-in service unavailable. Please retry.';
        if(error.status===429 && error.retryAfter) error.message=`Authentication limit reached. Try again in ${error.retryAfter} seconds.`;
        throw error;
      }
      return api(path,options,true);
    }
    sessionExpired();
  }
  return readApiResponse(resp);
}
function send(path, data, method='POST') { return api(path, {method, body:JSON.stringify(data)}); }
function toast(text) { notice = text; renderNotice(); setTimeout(() => {if (notice===text) {notice='';renderNotice()}}, 4400); }
function renderNotice() {
  $('.toast')?.remove();
  if (notice) document.body.insertAdjacentHTML('beforeend', `<div class="toast" role="status">${esc(notice)} <button id="close-toast" aria-label="Dismiss">×</button></div>`);
  $('#close-toast')?.addEventListener('click', ()=> {notice='';renderNotice()});
}
function icon(name, size=20) {
  const paths = {
    logo: '<path d="M3 11.4 12 3l9 8.4v9H3z"/><path d="M8.5 20.4v-7h7v7"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    arrow: '<path d="M5 12h14m-7-7 7 7-7 7"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    package: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/>',
    check: '<path d="m4 12 5 5L20 6"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/>',
    search: '<circle cx="10.8" cy="10.8" r="7.5"/><path d="m16.5 16.5 5 5"/>',
    close: '<path d="M18 6 6 18M6 6l12 12"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.1 0l3-3a5 5 0 0 0-7.1-7.1l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.1 0l-3 3a5 5 0 0 0 7.1 7.1l1.7-1.7"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
    circle: '<circle cx="12" cy="12" r="9"/>',
    history: '<path d="M3 12a9 9 0 1 0 2.5-6.2M3 4v5h5M12 7v5l4 2"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/><path d="m9 12 2 2 4-4"/>',
    chevron: '<path d="m9 18 6-6-6-6"/>',
    spark: '<path d="m12 3 1.7 6.3L20 11l-6.3 1.7L12 19l-1.7-6.3L4 11l6.3-1.7z"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>'
  };
  return `<svg aria-hidden="true" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24">${paths[name]||paths.circle}</svg>`;
}
const labelMode = m => m==='OFF' ? 'Off the Record' : 'On the Record';
function ackBadge(rec) {
 if (rec.mode==='OFF') return `<span class="badge badge-muted">${icon('lock',13)} Private</span>`;
 const map={NONE:['badge-muted','Not shared'],PENDING:['badge-amber','Awaiting handover acknowledgment'],CONFIRMED:['badge-green','Handover acknowledged'],DECLINED:['badge-red','Declined']};
 const [style,text]=map[rec.acknowledgment]||map.NONE;
 return `<span class="badge ${style}">${text}</span>`;
}
function acknowledgmentSummary(r) {
 if(r.mode==='OFF') return '';
 const handover={NONE:'Not requested',PENDING:'Awaiting acknowledgment',CONFIRMED:'Acknowledged',DECLINED:'Declined'};
 const returned={NONE:'Not returned yet',PENDING:'Awaiting lender acknowledgment',PARTIAL:'Partial return acknowledged',CONFIRMED:'All returned / completed'};
 return `<div class="detail-summary"><div><small>1. Item taken / given</small><strong class="small-strong">${handover[r.handover_acknowledgment]||handover[r.acknowledgment]}</strong></div><div><small>2. Returned / completed</small><strong class="small-strong">${returned[r.return_acknowledgment]||returned.NONE}</strong></div></div>`;
}
function authScreen(message='', recovery=null) {
 if(authConfig.provider==='supabase') {supabaseAuthScreen(message,recovery);return;}
 $('#app').innerHTML = `<div class="auth-wrap">
 <section class="auth-intro"><div class="brand brand-light"><span class="brand-mark">${icon('package',23)}</span><span>udhaar<span class="brand-dot">.</span></span></div>
 <div class="auth-intro-copy"><div class="eyebrow light-eyebrow">THE LITTLE THINGS MATTER</div><h1>Good things<br>are worth<br><em>remembering.</em></h1><p>That book you borrowed. The charger you lent. The things you meant to get back. All in one calm place.</p></div>
 <div class="auth-foot">✦ Less remembering. More living.</div></section>
 <section class="auth-panel"><div class="auth-box"><div class="auth-chip">${icon('shield',14)} Private by default</div><h2>${signup?'Make yourself at home.':'Welcome back.'}</h2><p>${signup?'Start keeping track of the things that matter.':'Your lending and borrowing, all accounted for.'}</p>
 <form id="auth-form">${signup?'<label>Your name<input name="name" required maxlength="100" placeholder="e.g. Alex" autocomplete="name" /></label>':''}
 <label>Email address<input name="email" type="email" required placeholder="you@example.com" autocomplete="email" /></label>
 <label>Password<input name="password" type="password" required minlength="8" placeholder="At least 8 characters" autocomplete="${signup?'new-password':'current-password'}" /></label>
 <button class="btn btn-primary full" type="submit">${signup?'Create my account':'Sign in'} ${icon('arrow',18)}</button><p class="form-error" id="auth-error" role="alert"></p></form>
 <div class="auth-switch">${signup?'Already have an account?':'New to Udhaar?'} <button id="switch-auth">${signup?'Sign in':'Create an account'}</button></div>
 <div class="auth-note">Your personal records are never visible to other Udhaar users unless you explicitly share them.</div></div></section></div>`;
 $('#switch-auth').onclick=()=>{signup=!signup;authScreen()};
 $('#auth-form').onsubmit=async e=>{e.preventDefault();const btn=$('#auth-form button[type=submit]');btn.disabled=true;const d=Object.fromEntries(new FormData(e.target));try {user=await send(signup?'/api/register':'/api/login',d);await loadRecords();}catch(err){$('#auth-error').textContent=err.message}finally{btn.disabled=false}};
}
function supabaseAuthScreen(message='', recovery=null) {
 $('#app').innerHTML=`<div class="auth-wrap">
 <section class="auth-intro"><div class="brand brand-light"><span class="brand-mark">${icon('package',23)}</span><span>udhaar<span class="brand-dot">.</span></span></div>
 <div class="auth-intro-copy"><div class="eyebrow light-eyebrow">THE LITTLE THINGS MATTER</div><h1>Good things<br>are worth<br><em>remembering.</em></h1><p>A simple place for the things you lend and borrow.</p></div></section>
 <section class="auth-panel"><div class="auth-box"><div class="auth-chip">${icon('shield',14)} Sign in with an email code</div>
 <h2>${otpSent?'Check your inbox.':signup?'Make yourself at home.':'Welcome back.'}</h2>
 <p>${otpSent?`Enter the sign-in code sent to ${esc(authEmail)}.`:'We will email you a one-time code. No password needed.'}</p>
 ${!authConfig.configured?'<p class="form-error" role="alert">Email sign-in is not configured yet. Ask the app administrator to complete setup.</p>':''}
 <form id="otp-form">${otpSent?'<label>Sign-in code<input name="code" required inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6,10}" minlength="6" maxlength="10" autofocus /></label>':`${signup?`<label>Your name<input name="name" required maxlength="100" autocomplete="name" value="${esc(authName)}" /></label>`:''}<label>Email address<input name="email" type="email" required maxlength="255" autocomplete="email" value="${esc(authEmail)}" /></label>`}
 <button class="btn btn-primary full" type="submit" ${!authConfig.configured?'disabled':''}>${otpSent?'Verify and continue':'Send sign-in code'} ${icon('arrow',18)}</button><p class="form-error" id="otp-error" role="alert">${esc(message)}</p></form>
 ${recovery?'<button id="retry-session" class="btn btn-secondary full">Retry session</button>':''}
 <div class="auth-switch">${otpSent?'<button id="change-email">Change email</button> <button id="resend-code" disabled>Resend code</button> ':''}<span>${signup?'Already have an account?':'New to Udhaar?'}</span> <button id="switch-auth">${signup?'Sign in':'Create an account'}</button></div>
 <div class="auth-note">Your personal records stay private unless you share a loan link.</div></div></section></div>`;
 $('#switch-auth')?.addEventListener('click',()=>{if(authSubmitting)return;signup=!signup;otpSent=false;authScreen()});
 $('#change-email')?.addEventListener('click',()=>{if(authSubmitting)return;otpSent=false;authScreen()});
 const retry=$('#retry-session');
 if(retry){
  const deadline=Date.now()+(recovery.status===429?recovery.retryAfter||60:0)*1000;
  const update=()=>{const remaining=Math.max(0,Math.ceil((deadline-Date.now())/1000));retry.disabled=remaining>0;retry.textContent=remaining?`Retry session in ${remaining}s`:'Retry session';};
  update();const timer=setInterval(()=>{if(!retry.isConnected){clearInterval(timer);return}update()},250);
  retry.onclick=()=>window.location.reload();
 }
 const resend=$('#resend-code');
 if(resend){resend.onclick=async()=>{if(authSubmitting||resend.disabled)return;authSubmitting=true;updateOtpControls();try{await requestOtpCode();toast('If eligible, another code has been sent.')}catch(err){$('#otp-error').textContent=err.message}finally{authSubmitting=false;updateOtpControls()}};}
 const form=$('#otp-form');
 $('input[name=email]',form)?.addEventListener('input',updateOtpControls);
 updateOtpControls();const timer=setInterval(()=>{if(!form.isConnected){clearInterval(timer);return}updateOtpControls()},250);
 form.onsubmit=async e=>{e.preventDefault();updateOtpControls();if(authSubmitting||$('button[type=submit]',form).disabled)return;const data=Object.fromEntries(new FormData(e.target));authSubmitting=true;updateOtpControls();
  try{if(!otpSent){authEmail=data.email.trim().toLowerCase();authName=(data.name||'').trim();await requestOtpCode();otpSent=true;authScreen();}
   else{user=await send('/api/auth/verify',{email:authEmail,code:data.code.trim(),name:authName});authConfig.has_session=true;otpSent=false;await loadRecords();}}
  catch(err){if(otpSent&&err.status===429)verifyRetryUntil=Date.now()+(err.retryAfter||60)*1000;$('#otp-error')?.replaceChildren(document.createTextNode(err.message));}
  finally{authSubmitting=false;updateOtpControls();}
 };
}
function topLayout(content) {
 $('#app').innerHTML=`<div class="layout"><aside class="sidebar" id="sidebar">
   <div class="brand"><span class="brand-mark">${icon('package',23)}</span><span>udhaar<span class="brand-dot">.</span></span></div>
   <div class="sidebar-caption">MY WORKSPACE</div><nav class="nav">
   <button data-tab="ALL" class="nav-link ${tab==='ALL'?'active':''}">${icon('grid',19)} Overview</button>
   <button data-tab="OFF" class="nav-link ${tab==='OFF'?'active':''}">${icon('lock',19)} Off the Record <span class="nav-count">${records.filter(r=>r.mode==='OFF').length}</span></button>
   <button data-tab="ON" class="nav-link ${tab==='ON'?'active':''}">${icon('users',19)} On the Record <span class="nav-count">${records.filter(r=>r.mode==='ON').length}</span></button>
   </nav><button id="invite-friends" class="btn btn-secondary">${icon('link',17)} Invite friends</button><div class="sidebar-spacer"></div><div class="sidebar-tip">${icon('spark',19)}<strong>Just a little reminder</strong><p>A record today saves an awkward conversation tomorrow.</p></div>
   <div class="sidebar-user"><span class="avatar">${esc((user.name||'U').slice(0,1).toUpperCase())}</span><span class="sidebar-username"><strong>${esc(user.name)}</strong><small>${esc(user.email)}</small></span><button title="Sign out" aria-label="Sign out" id="logout">${icon('logout',19)}</button></div>
 </aside><main class="main"><div class="mobilebar"><button aria-label="Toggle navigation" id="toggle-nav">${icon('menu')}</button><div class="brand"><span class="brand-mark">${icon('package',19)}</span><span>udhaar<span class="brand-dot">.</span></span></div></div>${content}</main></div>`;
 $$('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;activeRecord=null;render()});
 $('#invite-friends').onclick=()=>showSignupShare();
 $('#logout').onclick=async()=>{try{await send(authConfig.provider==='supabase'?'/api/auth/logout':'/api/logout',{});clearSignedInState();authScreen()}catch(err){toast(err.message)}};
 $('#toggle-nav')?.addEventListener('click',()=>$('#sidebar').classList.toggle('sidebar-open'));
}
function dashboard() {
 const lent=records.filter(r=>r.direction==='LENT'&&r.outstanding_quantity>0);
 const borrowed=records.filter(r=>r.direction==='BORROWED'&&r.outstanding_quantity>0);
 const overdue=records.filter(r=>r.outstanding_quantity>0&&r.due_date&&r.due_date<today());
 const titles={ALL:['Your belongings,','accounted for.'],OFF:['Off the Record,','just for you.'],ON:['On the Record,','together.']};
 const desc={ALL:'Less wondering who has what. More peace of mind.', OFF:'Your private notes. No shared links, no awkward follow-ups.', ON:'Shared records with clear acknowledgments and return tracking.'};
 const list=records.filter(r=>tab==='ALL'||r.mode===tab);
 topLayout(`<header class="pagehead"><div class="page-eyebrow">YOUR SPACE <span>✦</span> ${new Date().toLocaleDateString(undefined,{month:'long',year:'numeric'}).toUpperCase()}</div>
 <div class="headerline"><div><h1>${titles[tab][0]}<br><em>${titles[tab][1]}</em></h1><p>${desc[tab]}</p></div><button id="new-record" class="btn btn-primary">${icon('plus',18)} New record</button></div></header>
 <section class="summary-grid"><div class="metric"><span class="metric-icon mint">${icon('arrow',18)}</span><span class="metric-label">Currently lent out</span><strong>${lent.reduce((n,r)=>n+r.outstanding_quantity,0)}</strong><small>items waiting to come back</small></div>
 <div class="metric"><span class="metric-icon lavender">${icon('package',18)}</span><span class="metric-label">Currently borrowed</span><strong>${borrowed.reduce((n,r)=>n+r.outstanding_quantity,0)}</strong><small>items you're holding</small></div>
 <div class="metric"><span class="metric-icon peach">${icon('clock',18)}</span><span class="metric-label">Past due</span><strong>${overdue.length}</strong><small>records to follow up on</small></div></section>
 <section class="records-section"><div class="sectionhead"><div><div class="section-eyebrow">THE THINGS YOU'RE TRACKING</div><h2>${tab==='ALL'?'All records':labelMode(tab)} <span>${list.length}</span></h2></div><div class="search-wrap">${icon('search',17)}<input id="search" type="search" placeholder="Find an item or person…" autocomplete="off"/></div></div>
 <div class="filterbar"><button class="filter ${tab==='ALL'?'chosen':''}" data-filter="ALL">All records</button><button class="filter ${tab==='OFF'?'chosen':''}" data-filter="OFF">${icon('lock',14)} Off the Record</button><button class="filter ${tab==='ON'?'chosen':''}" data-filter="ON">${icon('users',14)} On the Record</button></div>
 <div class="record-list" id="record-list"></div></section>
 <footer class="footerline">Made for life's little exchanges. <span>Udhaar MVP · Your private entries stay yours.</span></footer>`);
 function showList(q='') {
  const filtered=list.filter(r=>`${r.item_name} ${r.contact_name} ${r.category}`.toLowerCase().includes(q.toLowerCase()));
  $('#record-list').innerHTML=filtered.length ? filtered.map(rec=>{
   const isDue=rec.due_date&&rec.due_date<today()&&rec.outstanding_quantity>0;
   return `<button class="record-card" data-rec="${rec.id}"><span class="item-icon">${icon('package',23)}</span><span class="record-main"><strong>${esc(rec.item_name)}</strong><span>${rec.direction==='LENT'?'Lent to':'Borrowed from'} <b>${esc(rec.contact_name)}</b> · ${prettyDate(rec.loan_date)}</span></span><span class="record-middle">${ackBadge(rec)}<span class="record-quantity">${rec.outstanding_quantity} of ${rec.quantity} outstanding</span></span><span class="record-right"><span class="due ${isDue?'due-late':''}">${rec.settlement==='RETURNED'?'All returned':isDue?'Overdue':rec.due_date?'Due '+prettyDate(rec.due_date):'No due date'}</span>${icon('chevron',19)}</span></button>`
  }).join('') : `<div class="empty"><span class="empty-graphic">${icon('package',30)}</span><h3>${q?'Nothing found.':'A fresh start.'}</h3><p>${q?'Try another search.':'Create your first record to remember what you lend or borrow.'}</p>${q?'':'<button class="btn btn-secondary" id="empty-add">+ Add a record</button>'}</div>`;
  $$('[data-rec]').forEach(b=>b.onclick=()=>openDetails(b.dataset.rec));
  $('#empty-add')?.addEventListener('click',openNew);
 }
 showList();
 $('#search').oninput=e=>showList(e.target.value);
 $$('[data-filter]').forEach(b=>b.onclick=()=>{tab=b.dataset.filter;render()});
 $('#new-record').onclick=openNew;
}
function render(){ if (!user) authScreen();else dashboard();renderNotice() }
function modal(html) {
 const el=document.createElement('div'); el.className='modal-backdrop'; el.innerHTML=`<div class="modal" role="dialog" aria-modal="true"><button class="close-modal" aria-label="Close">${icon('close',21)}</button>${html}</div>`;
 document.body.appendChild(el);el.addEventListener('click',e=>{if(e.target===el)el.remove()});$('.close-modal',el).onclick=()=>el.remove();document.addEventListener('keydown',function escape(e){if(e.key==='Escape'){el.remove();document.removeEventListener('keydown',escape)}},{once:true});return el;
}
function openNew(){
 const el=modal(`<div class="modal-eyebrow">A LITTLE SOMETHING TO REMEMBER</div><h2>New lending record</h2><p>Start with the essentials. Everything else can wait.</p>
 <form id="record-form"><div class="switch-group"><label class="choice"><input name="direction" type="radio" value="LENT" checked/><span>↗ &nbsp; I lent something</span></label><label class="choice"><input name="direction" type="radio" value="BORROWED"/><span>↙ &nbsp; I borrowed something</span></label></div>
 <div class="field-grid"><label class="field wide">What item?<input name="item_name" required maxlength="160" placeholder="e.g. Power drill" autofocus /></label><label class="field wide">Who with?<input name="contact_name" required maxlength="100" placeholder="e.g. Rahul" /></label>
 <label class="field">Category<select name="category"><option>Tools</option><option>Books</option><option>Electronics</option><option>Documents</option><option>Clothing</option><option>Equipment</option><option>Other</option></select></label><label class="field">Quantity<input name="quantity" type="number" required min="1" max="100000" value="1" /></label>
 <label class="field">Date lent / borrowed<input name="loan_date" type="date" required value="${today()}" /></label><label class="field">Expected return <span>(optional)</span><input name="due_date" type="date" /></label>
 <label class="field wide">A note to yourself <span>(optional)</span><textarea name="notes" rows="2" maxlength="2000" placeholder="Any details worth remembering…"></textarea></label></div>
 <div class="form-subtitle">How would you like to save it?</div><div class="mode-options"><label class="mode-option"><input type="radio" name="mode" value="OFF" checked/><span class="mode-option-content">${icon('lock',21)}<strong>Off the Record</strong><small>Private. Only you can see it.</small></span></label><label class="mode-option"><input type="radio" name="mode" value="ON"/><span class="mode-option-content">${icon('users',21)}<strong>On the Record</strong><small>Share a link for acknowledgment and returns.</small></span></label></div>
 <div class="modal-actions"><button type="button" class="btn btn-quiet" id="cancel-new">Cancel</button><button class="btn btn-primary" type="submit">Save record ${icon('arrow',16)}</button></div><p class="form-error" id="new-error"></p></form>`);
 $('#cancel-new',el).onclick=()=>el.remove();
 $('#record-form',el).onsubmit=async(e)=>{e.preventDefault();const f=e.target, values=Object.fromEntries(new FormData(f));values.quantity=Number(values.quantity);if(!values.due_date)values.due_date=null;try{const rec=await send('/api/records',values);el.remove();await loadRecords();toast('Record saved.');openDetails(rec.id);}catch(err){$('#new-error',el).textContent=err.message}};
}
async function openDetails(id) {
 let r;try{r=await api(`/api/records/${id}`)}catch(err){toast(err.message);return}
 const modalEl=modal(`<div class="detail-top"><div class="modal-eyebrow">${labelMode(r.mode).toUpperCase()}</div><h2>${esc(r.item_name)}</h2><p>${r.direction==='LENT'?'Lent to':'Borrowed from'} <strong>${esc(r.contact_name)}</strong></p><div class="detail-tags">${ackBadge(r)}<span class="badge badge-muted">${esc(r.category)}</span></div></div>
 <div class="detail-summary"><div><small>Original quantity</small><strong>${r.quantity}</strong></div><div><small>Still outstanding</small><strong>${r.outstanding_quantity}</strong></div><div><small>Due date</small><strong class="small-strong">${prettyDate(r.due_date)}</strong></div></div>
 ${acknowledgmentSummary(r)}
 ${r.notes?`<div class="detail-notes"><strong>Note to self</strong><p>${esc(r.notes)}</p></div>`:''}
 <div class="detail-actions">${r.mode==='OFF'||(r.mode==='ON'&&r.acknowledgment==='NONE') ? `<button id="edit-action" class="btn btn-secondary">Edit details</button>` : ''}${r.mode==='OFF' && r.settlement!=='RETURNED'?`<button id="share-action" class="btn btn-secondary">${icon('link',17)} Move to On the Record</button>`:''}
 ${r.mode==='ON'?`<button id="share-action" class="btn btn-secondary">${icon('link',17)} ${r.acknowledgment==='NONE'?'Share loan link':'Replace loan link'}</button>`:''}
 ${r.outstanding_quantity>r.pending_quantity && (r.mode==='OFF'||r.acknowledgment==='CONFIRMED')?`<button id="return-action" class="btn btn-primary">${icon('check',17)} ${r.mode==='OFF'?'Mark returned':r.direction==='LENT'?'Acknowledge item returned':'Request return acknowledgment'}</button>`:''}</div>
 ${r.mode==='ON' ? `<p class="fine-print">${r.acknowledgment==='NONE'?'No loan link created yet.':'Shared-link acknowledgment does not verify someone’s identity.'} Loan links expire after 30 days. Replacing a link invalidates the old one and requires acknowledgment again.</p>` : '<p class="fine-print">Only you can see this record. You can choose to share it later.</p>'}
 ${r.returns.length ? `<h3 class="small-header">Return activity</h3><div class="return-list">${r.returns.map(a=>`<div class="return-row"><div><strong>${a.quantity} item(s)</strong><span>${a.status==='PENDING'?'Awaiting return acknowledgment':a.status==='CONFIRMED'?'Return acknowledged':'Cancelled'}</span></div>${a.status==='PENDING' && r.direction==='LENT'?`<button class="btn btn-small confirm-return" data-return="${a.id}">Acknowledge return</button>`:''}</div>`).join('')}</div>`:''}
 <h3 class="small-header">History</h3><div class="timeline">${r.events.map(a=>`<div class="timeline-entry"><i></i><div><strong>${esc(a.description)}</strong><small>${new Date(a.created_at).toLocaleString()}</small></div></div>`).join('')}</div>`);
 $('#edit-action',modalEl)?.addEventListener('click',()=>{modalEl.remove();openEdit(r)});
 $('#share-action',modalEl)?.addEventListener('click',async()=>{try{const data=await send(`/api/records/${r.id}/share`,{});modalEl.remove();await loadRecords();showShare(window.location.origin+data.path)}catch(err){toast(err.message)}});
 $('#return-action',modalEl)?.addEventListener('click',()=>{modalEl.remove();openReturn(r)});
 $$('.confirm-return',modalEl).forEach(btn=>btn.onclick=async()=>{try{await send(`/api/records/${r.id}/returns/${btn.dataset.return}/confirm`,{});modalEl.remove();await loadRecords();toast('Return confirmed.');openDetails(r.id)}catch(err){toast(err.message)}});
}
function openEdit(r) {
 const el=modal(`<div class="modal-eyebrow">UPDATE YOUR RECORD</div><h2>Edit record</h2><p>Keep the item name, date, and private notes up to date.</p>
 <form id="edit-form"><label class="field">Item name<input name="item_name" value="${esc(r.item_name)}" required maxlength="160" /></label><br>
 <label class="field">Due date<input name="due_date" type="date" value="${esc(r.due_date||'')}" /></label><br>
 <label class="field">Notes<textarea name="notes" rows="3" maxlength="2000">${esc(r.notes||'')}</textarea></label>
 <div class="modal-actions"><button type="button" class="btn btn-quiet" id="cancel-edit">Cancel</button><button class="btn btn-primary" type="submit">Save changes</button></div><p class="form-error" id="edit-error"></p></form>`);
 $('#cancel-edit',el).onclick=()=>el.remove();
 $('#edit-form',el).onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));if(!data.due_date)data.due_date=null;
 try{await send(`/api/records/${r.id}`,data,'PATCH');el.remove();await loadRecords();toast('Record updated.');openDetails(r.id)}catch(err){$('#edit-error',el).textContent=err.message}};
}
function showShare(url) {
 const el=modal(`<div class="share-illustration">${icon('link',30)}</div><div class="modal-eyebrow">SHARE LOAN LINK</div><h2>Share this loan.</h2><p>Copy and send this link through your messaging app. Anyone holding it can acknowledge and use the same link for returns without signing up.</p><label class="field">Loan link<input id="share-url" value="${esc(url)}" readonly /></label><button id="copy-share" class="btn btn-primary full">Copy loan link ${icon('link',17)}</button><div class="privacy-hint">You are responsible for who you send this link to. Anyone with it can view this loan, acknowledge it, and act as the other person for returns. The link expires in 30 days. Identity is not verified.</div>`);
 $('#copy-share',el).onclick=async()=>{try{await navigator.clipboard.writeText(url);toast('Loan link copied.')}catch {$('#share-url',el).focus();$('#share-url',el).select();toast('Select the link and copy it.')}};
}
function showSignupShare() {
 const url = window.location.origin + '/signup';
 const el=modal(`<div class="modal-eyebrow">INVITE FRIENDS</div><h2>Share Udhaar.</h2><p>Copy this signup link and send it through your messaging app. It lets friends create their own account.</p><label class="field">Signup link<input id="signup-url" value="${esc(url)}" readonly /></label><button id="copy-signup" class="btn btn-primary full">Copy signup link ${icon('link',17)}</button>`);
 $('#copy-signup',el).onclick=async()=>{try{await navigator.clipboard.writeText(url);toast('Signup link copied.')}catch{$('#signup-url',el).focus();$('#signup-url',el).select();toast('Select the link and copy it.')}};
}
function openReturn(r){
 const available=r.outstanding_quantity-r.pending_quantity;
 const el=modal(`<div class="modal-eyebrow">RETURN TRACKING</div><h2>Update a return</h2><p>${esc(r.item_name)} — ${available} item(s) available to record as returned.</p><form id="return-form"><label class="field">Quantity returned<input type="number" name="quantity" required min="1" max="${available}" value="${available}" /></label><div class="privacy-hint">${r.mode==='OFF'?'This return will be marked complete in your private record.':r.direction==='LENT'?'You are the lender, so your confirmation completes this return.':'The lender must confirm receipt through their shared link.'}</div><div class="modal-actions"><button class="btn btn-quiet" type="button" id="cancel-return">Cancel</button><button class="btn btn-primary" type="submit">Save return</button></div><p class="form-error" id="return-error"></p></form>`);
 $('#cancel-return',el).onclick=()=>el.remove();
 $('#return-form',el).onsubmit=async e=>{e.preventDefault();try{const response=await send(`/api/records/${r.id}/returns`,{quantity:Number(new FormData(e.target).get('quantity'))});el.remove();await loadRecords();toast(response.status==='PENDING'?'Return proposed. Awaiting the lender.':'Return saved.');openDetails(r.id);}catch(err){$('#return-error',el).textContent=err.message}};
}
async function loadRecords(){records=await api('/api/records');render()}
async function guestPage(token){
 const wrap = $('#app');
 async function load(){
  let r;try{r=await api(`/api/share/${encodeURIComponent(token)}`)}catch(err){wrap.innerHTML=`<div class="guest-wrap"><div class="guest-card"><div class="brand center"><span class="brand-mark">${icon('package',22)}</span>udhaar<span class="brand-dot">.</span></div><h2>Link unavailable</h2><p>${esc(err.message)}. Ask the sender for a new loan link.</p></div></div>`;return}
  wrap.innerHTML=`<div class="guest-wrap"><div class="guest-card"><div class="brand center"><span class="brand-mark">${icon('package',22)}</span>udhaar<span class="brand-dot">.</span></div><div class="guest-eyebrow">A LITTLE SOMETHING TO CONFIRM</div>
  <div class="guest-icon">${icon('package',27)}</div><h1>${esc(r.item_name)}</h1><p class="guest-intro">${esc(r.owner_name)} shared a loan link for you to acknowledge and track returns. No account is needed.</p>
  <div class="guest-facts"><div><small>Record direction</small><strong>${r.direction==='LENT'?`${esc(r.owner_name)} lent this item`:`${esc(r.owner_name)} borrowed this item`}</strong></div><div><small>Other person</small><strong>${esc(r.contact_name)}</strong></div><div><small>Quantity</small><strong>${r.quantity}</strong></div><div><small>Date</small><strong>${prettyDate(r.loan_date)}</strong></div>${r.due_date?`<div><small>Expected return</small><strong>${prettyDate(r.due_date)}</strong></div>`:''}</div>
  ${r.invitation_state==='PENDING'?`<p class="guest-question">1. Acknowledge the handover: ${r.direction==='LENT'?'did you take / borrow this item?':'did you give / lend this item?'}</p><div class="guest-buttons"><button id="accept-invite" class="btn btn-primary">${icon('check',18)} ${r.direction==='LENT'?'I took / borrowed this item':'I gave / lent this item'}</button><button id="decline-invite" class="btn btn-secondary">No, decline</button></div>`:`<div class="guest-confirmed">${icon('shield',20)} The item handover was acknowledged through this link. Return acknowledgment is separate; keep this link to complete it. Identity is not verified.</div>`}
  ${acknowledgmentSummary(r)}
  ${r.invitation_state==='ACCEPTED'?`<div class="guest-return"><h3>2. Return acknowledgment</h3><p>${r.outstanding_quantity===0?'All items returned. This loan is complete.':`${r.outstanding_quantity} of ${r.quantity} still outstanding`}</p>${r.pending_quantity?`<p>${r.pending_quantity} item(s) awaiting lender acknowledgment.</p>`:''}${r.outstanding_quantity > r.pending_quantity ?`<button id="guest-return" class="btn btn-secondary">${r.direction==='BORROWED'?'Acknowledge item returned':'Report item returned'}</button>`:''}${r.returns.filter(x=>x.status==='PENDING'&&r.direction==='BORROWED').map(x=>`<div class="return-row"><div><strong>${x.quantity} item(s)</strong><span>Borrower requested return confirmation</span></div><button data-guest-confirm="${x.id}" class="btn btn-small">Acknowledge return</button></div>`).join('')}</div>`:''}
  <div class="guest-disclaimer">Anyone holding this link can view this loan and act as the other person for acknowledgment and returns. The sender is responsible for sharing it with the right person. Expires ${prettyDate(r.link_expires_at.slice(0,10))}.</div></div><div class="guest-footer">Udhaar — lend it, track it, get it back.</div></div>`;
  $('#accept-invite')?.addEventListener('click',async()=>{try{await send(`/api/share/${token}/respond`,{accept:true});toast('Record acknowledged.');load()}catch(err){toast(err.message)}});
  $('#decline-invite')?.addEventListener('click',async()=>{try{await send(`/api/share/${token}/respond`,{accept:false});wrap.innerHTML='<div class="guest-wrap"><div class="guest-card"><div class="brand center">udhaar.</div><h2>Acknowledgment declined</h2><p>The record owner can see that you declined. No return or agreement was recorded.</p></div></div>'}catch(err){toast(err.message)}});
  $('#guest-return')?.addEventListener('click',()=>{
    const av=r.outstanding_quantity-r.pending_quantity;
    const el=modal(`<div class="modal-eyebrow">SHARED RETURN TRACKING</div><h2>${r.direction==='BORROWED'?'Acknowledge return':'Report a return'}</h2><form id="guest-return-form"><label class="field">How many returned?<input name="quantity" type="number" min="1" max="${av}" value="${av}" required /></label><p class="privacy-hint">${r.direction==='BORROWED'?'You are the lender. This acknowledges that the item was returned to you.':'The lender must acknowledge receipt before this return is complete.'}</p><button type="submit" class="btn btn-primary full">Save</button><p class="form-error" id="guest-return-error"></p></form>`);
    $('#guest-return-form',el).onsubmit=async e=>{e.preventDefault();try{await send(`/api/share/${token}/returns`,{quantity:Number(new FormData(e.target).get('quantity'))});el.remove();toast('Return update saved.');load()}catch(err){$('#guest-return-error',el).textContent=err.message}};
  });
  $$('[data-guest-confirm]').forEach(b=>b.onclick=async()=>{try{await send(`/api/share/${token}/returns/${b.dataset.guestConfirm}/confirm`,{});toast('Return confirmed.');load()}catch(err){toast(err.message)}});
 }
 await load();
}
(async function init(){
 try{csrf=(await api('/api/csrf')).csrf;
 const guestMatch=window.location.pathname.match(/^\/share\/([A-Za-z0-9_-]+)\/?$/);
 if(guestMatch){await guestPage(guestMatch[1]);return}
 authConfig=await api('/api/auth/config');
 if(authConfig.provider==='supabase'&&!authConfig.has_session){authScreen();return}
 try{user=await api('/api/me');await loadRecords()}catch(error){
  user=null;records=[];activeRecord=null;
  authScreen(error.status===401?'Your session expired. Please sign in again.':error.message,error.status===401?null:error);
 }
 }catch(e){$('#app').innerHTML=`<div class="loading-screen">Could not start Udhaar: ${esc(e.message)}. Refresh to retry.</div>`}
})();
