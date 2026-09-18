// Browser regression/screenshot run against the disposable fixture ONLY.
// Start the seeded isolated server on port 8855 first (see testing report).
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const base = 'http://127.0.0.1:8855';
const session = 'sentinel-full-qa';
const results = [];
const shots = path.resolve('docs/screenshots');
const password = 'Synthetic-demo-only-passphrase-981!';
fs.mkdirSync(shots, { recursive: true });
function browser(...args) {
  return execFileSync('npx', ['--yes', 'agent-browser', '--session', session, ...args], { encoding: 'utf8', timeout: 30000, maxBuffer: 2e6 });
}
function evaluate(js) { return browser('eval', js); }
function check(expression, message) { evaluate(`if (!(${expression})) throw new Error(${JSON.stringify(message)}); true`); }
function open(route) { browser('open', base + route); browser('wait', '--load', 'networkidle'); browser('snapshot', '-i'); }
function screenshot(name) { browser('screenshot', path.join(shots, name + '.png')); }
function login(email) {
  open('/administration');
  browser('fill', '#userEmail', email);
  browser('fill', '#userPassword', password);
  browser('click', '#loginUser');
  browser('wait', '--load', 'networkidle');
  check('document.getElementById("authNotice").textContent.includes("Logged in as")', 'Login should succeed');
}
function step(name, fn) {
  try { fn(); results.push({ name, status: 'PASS' }); console.log('PASS ' + name); }
  catch (error) { results.push({ name, status: 'FAIL', detail: String(error.stderr || error.stdout || 'Browser command failed').slice(0, 1500) }); console.log('FAIL ' + name); }
  fs.writeFileSync('docs/testing/browser-results.json', JSON.stringify({ date: new Date().toISOString(), base, dataset: 'Synthetic disposable fixture only', results }, null, 2));
}

step('Administrator login and cleared password', () => {
  login('admin@example.test');
  check('document.getElementById("userPassword").value === ""', 'Password should clear after login');
  check('!document.getElementById("userManagement").classList.contains("hidden")', 'Admin account tools should be visible');
  browser('set', 'viewport', '1366', '900');
  evaluate('scrollTo(0, 0)');
  screenshot('administration');
});
step('Dashboard loads saved SOW and live counts', () => {
  open('/?contract_id=1');
  check('document.getElementById("activeSow").value === "1"', 'Selected SOW should load');
  check('Number(document.getElementById("sowCount").textContent) >= 3', 'SOW count should reflect fixture data');
  screenshot('dashboard');
});
step('Scope analysis produces evidence and clears inputs', () => {
  browser('fill', '#ticketTitle', 'Add Coinbase cryptocurrency checkout');
  browser('fill', '#ticketDescription', 'Add Coinbase Commerce as a second payment provider with cryptocurrency payment webhooks.');
  browser('fill', '#acceptance', 'A successful Coinbase cryptocurrency payment marks the customer order as paid.');
  browser('fill', '#externalKey', 'DEMO-104');
  browser('fill', '#hours', '24');
  browser('click', '#analyseTicket');
  browser('wait', '--load', 'networkidle');
  check('document.getElementById("decisionBadge").textContent === "OUT OF SCOPE"', 'Expected out-of-scope decision');
  check('document.querySelectorAll("#evidenceList .evidence").length > 0', 'Clause evidence should render');
  check('document.getElementById("ticketTitle").value === ""', 'Successful submission should clear ticket title');
  evaluate('document.getElementById("resultPanel").scrollIntoView({block:"start"})');
  screenshot('scope-analysis');
});
step('Change-order draft calculates price and links to approval', () => {
  browser('fill', '#hourlyCost', '80');
  browser('fill', '#margin', '0.36');
  browser('click', '#createQuote');
  browser('wait', '--load', 'networkidle');
  check('/3,?000/.test(document.getElementById("quoteResult").textContent)', 'Expected 3000 price');
  check('!document.getElementById("quoteApproval").classList.contains("hidden")', 'Approval link should be visible');
  evaluate('document.getElementById("quotePanel").scrollIntoView({block:"start"})');
  screenshot('change-order');
});
step('History is populated and refresh starts at top', () => {
  browser('click', '.sidebar a[href$="#historyPanel"]');
  browser('click', '#loadHistory');
  browser('wait', '--load', 'networkidle');
  check('document.querySelectorAll("#historyList .evidence").length >= 3', 'History should contain saved tickets');
  evaluate('document.documentElement.style.scrollBehavior="auto"; document.getElementById("historyPanel").scrollIntoView({behavior:"instant",block:"start"})');
  screenshot('history');
  browser('reload');
  browser('wait', '--load', 'networkidle');
  check('scrollY === 0 && location.hash === "" && location.search.includes("contract_id=1")', 'Refresh must retain contract but reset scroll/hash');
});
step('Library search and document view', () => {
  open('/documents');
  check('document.querySelectorAll("#library .card").length >= 4', 'Library should show SOWs and amendment');
  screenshot('document-library');
  browser('fill', '#search', 'Laboratory');
  check('document.querySelectorAll("#library .card").length === 1', 'Search should narrow to one document');
  open('/documents/3');
  check('document.getElementById("content").value.includes("Stripe")', 'Document text should load');
  screenshot('document-editor');
});
step('Editing saves a new revision and preserves original', () => {
  browser('click', '#edit');
  browser('fill', '#version', '2.0');
  browser('fill', '#content', '1.1 Deliverable: Build a customer portal.\n\n4.1 Payment: Stripe checkout and Stripe webhooks are included.\n\n7.1 Deliverable: Add a reporting dashboard.');
  browser('click', '#save');
  browser('wait', '--load', 'networkidle');
  check('location.pathname !== "/documents/3" && document.getElementById("version").value === "2.0"', 'A new revision should open');
  evaluate(`(async()=>{const r=await fetch('/api/contracts/3');const d=await r.json();if(d.version!=='1.0')throw Error('Original overwritten');return true})()`);
});
step('PM reviewer approves another user request with a recorded reason', () => {
  open('/administration'); browser('click', '#logoutUser'); browser('wait', '--load', 'networkidle');
  login('pm@example.test');
  open('/approvals');
  browser('click', '#requestList article:first-child button');
  browser('wait', '--load', 'networkidle');
  check('!document.getElementById("approve").disabled', 'PM should be eligible for another user SOW');
  browser('fill', '#decisionReason', 'Synthetic QA review: deliverables, exclusions and exact version were checked.');
  browser('click', '#approve');
  browser('wait', '--load', 'networkidle');
  check('document.getElementById("reviewNotice").textContent.includes("APPROVED")', 'Final approval decision should display');
  evaluate('document.documentElement.style.scrollBehavior="auto"; document.getElementById("requestList").parentElement.scrollIntoView({behavior:"instant",block:"start"})');
  screenshot('approvals');
});
step('Unsafe-looking document titles render as text', () => {
  evaluate(`(async()=>{const csrf=(await (await fetch('/api/security/csrf')).json()).csrf_token;const headers={'Content-Type':'application/json','X-CSRF-Token':csrf};const r=await fetch('/api/contracts/text',{method:'POST',headers,body:JSON.stringify({title:'<img src=x onerror="window.qaXss=1">',content:'1.1 Deliverable: This is synthetic XSS escaping test content.'})});if(r.status!==201)throw Error('Fixture failed');const d=await r.json();sessionStorage.setItem('qaXssDocId',d.id);return true})()`);
  open('/documents');
  check('!window.qaXss && !document.querySelector("#library h2 img")', 'Title should not execute HTML');
  evaluate(`(async()=>{const token=(await (await fetch('/api/security/csrf')).json()).csrf_token;const id=sessionStorage.getItem('qaXssDocId');const r=await fetch('/api/contracts/'+id,{method:'DELETE',headers:{'X-CSRF-Token':token}});if(!r.ok)throw Error('Fixture cleanup failed');return true})()`);
});
step('Mobile route layout has no horizontal overflow', () => {
  browser('set', 'viewport', '390', '844');
  for (const route of ['/', '/documents', '/documents/1', '/documents/new', '/administration', '/approvals']) {
    open(route);
    check('document.documentElement.scrollWidth <= innerWidth', 'Horizontal overflow at ' + route);
  }
  open('/'); screenshot('mobile-dashboard');
  browser('set', 'viewport', '1366', '900');
});
step('Viewer cannot submit approval requests', () => {
  open('/administration'); browser('click', '#logoutUser'); browser('wait', '--load', 'networkidle');
  login('viewer@example.test');
  open('/approvals');
  check('document.getElementById("submitApproval").disabled', 'Viewer submission button must be disabled');
  evaluate(`(async()=>{const token=(await (await fetch('/api/security/csrf')).json()).csrf_token;const r=await fetch('/api/contracts/text',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify({title:'Forbidden fixture',content:'This must not be saved by a viewer account.'})});if(r.status!==403)throw Error('Viewer write not denied');return true})()`);
});
step('No uncaught browser errors', () => {
  const errors = browser('errors').trim();
  if (errors && errors !== 'No errors') throw new Error(errors);
});
browser('close');
if (results.some(row => row.status === 'FAIL')) process.exitCode = 1;
