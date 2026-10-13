import assert from 'node:assert/strict';
import { chromium } from '@playwright/test';

const tickets = [
  { id: 101, type: 'customer_order', requester: 'Tauhid Zaman', subject: 'Bulldog tee', description: 'Needs a tee in size S.', status: 'open', sku: 'CC-TEE-WHITE', size: 'S', quantity: 1, lease_id: null, invoice_id: 501, created_at: '2026-08-31T09:15:00-04:00' },
  { id: 102, type: 'rent_notice', requester: 'Elm City Properties', subject: 'Rent due', description: 'Email: shop rent due in 2 days.', status: 'open', sku: null, size: null, quantity: null, lease_id: 1, invoice_id: null, created_at: '2026-08-31T11:05:00-04:00' },
  { id: 103, type: 'price_override', requester: 'Yale AI Club', subject: 'Bulk hoodie discount', description: 'Student org wants 20 hoodies, size M, asking for a bulk discount.', status: 'open', sku: 'CC-HOOD-NAVY', size: 'M', quantity: 20, lease_id: null, invoice_id: null, created_at: '2026-08-31T16:55:00-04:00' },
];
const event = {
  timestamp: '2026-10-11T18:30:00Z', ticket_id: 102, agent_name: 'facilities',
  action: 'mcp_tool_call', arguments: { tool: 'check_lease_and_rent', arguments: { ticket_id: 102 } },
  result: { ok: true, rent_amount: 2400 }, iteration: 2, delegation_depth: 1,
  approval_required: false, status: 'completed', stop_reason: null, message: 'mcp_tool_call',
};
let cash = 3400;
let runPosts = 0;
let createdTicketPosts = 0;
let approvalPosts = 0;
let resetPosts = 0;
let ticketHistoryRequests = 0;
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const pageErrors = [];
page.on('pageerror', error => pageErrors.push(error.message));
page.on('console', message => { if (message.type() === 'error') pageErrors.push(message.text()); });
await page.route('http://localhost:8000/api/**', async route => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  const reply = async (value, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value), headers: { 'access-control-allow-origin': '*' } });
  if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': 'content-type' } });
  if (path === '/api/tickets' && request.method() === 'POST') {
    createdTicketPosts++;
    const input = request.postDataJSON();
    const created = { id: 104, type: 'dashboard_entry', requester: 'Not provided', subject: input.subject, description: input.description, status: 'open', sku: null, size: null, quantity: null, lease_id: null, invoice_id: null, created_at: '2026-08-31', resolution: null };
    tickets.push(created);
    return reply(created, 201);
  }
  if (path === '/api/tickets') return reply({ tickets, shop_date: '2026-08-31' });
  if (path === '/api/cash') return reply({ checking_balance: cash, available_cash: cash, cash_accounts: [{ name: 'checking', balance: cash, date: '2026-08-31' }] });
  if (path === '/api/events') {
    const ticketId = new URL(request.url()).searchParams.get('ticket_id');
    if (ticketId === '102') ticketHistoryRequests++;
    const events = ticketId === null || ticketId === '102' ? [event] : [];
    return reply({ events, limit: 200, count: events.length });
  }
  if (path === '/api/tickets/102/run') {
    runPosts++;
    await new Promise(resolve => setTimeout(resolve, 350));
    return reply({ ticket_id: 102, status: 'needs_approval', final_reasoning: 'Rent requires human approval.', findings: [{ fact: 'Rent amount is $2,400.', source: 'check_lease_and_rent', verified: true }], proposed_actions: [{ action: 'Pay rent', owner: 'accounting', action_type: 'payment', details: 'Pay monthly rent.', amount: 2400, available_cash: 3400, vendor_id: null, vendor_has_open_unpaid_invoices: null, reference_type: 'lease', reference_id: 1, account: 'checking', requires_human_approval: true, completed: false }], dependencies: [], approval_requirements: [{ action: 'Pay rent', reason: 'Human approval required.', required: true }], pending_approvals: [{ approval_id: 'test-approval', ticket_id: 102, action: 'Pay rent', action_type: 'payment', details: 'Pay monthly rent.', amount: 2400, account: 'checking', reference_type: 'lease', reference_id: 1, status: 'pending' }], iterations: 3, delegations: 2, stop_reason: null });
  }
  if (path === '/api/approvals/test-approval') { approvalPosts++; cash = 1000; return reply({ approval_id: 'test-approval', ticket_id: 102, status: 'executed', decision: 'approve', database_changed: true, message: 'Approved payment executed atomically through MCP.', result: { new_balance: 1000 } }); }
  if (path === '/api/reset') { resetPosts++; cash = 3400; return reply({ status: 'reset', message: 'Working database restored.', cleared_approvals: 0 }); }
  return reply({ detail: 'Unknown mock route' }, 404);
});

try {
  await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' });
  await page.getByRole('heading', { name: 'Operations', exact: true }).waitFor();
  assert.equal(await page.locator('.ticket-table tbody tr').count(), 3);
  assert.equal(await page.locator('.agent-module').count(), 5);
  await page.getByText('$3,400.00').first().waitFor();
  assert.equal(await page.getByText('SYSTEM ONLINE').count(), 1);
  console.log('PASS: live tickets, five agents, checking balance, connected state');

  await page.getByRole('button', { name: 'New Ticket' }).click();
  await page.getByRole('dialog', { name: 'New ticket' }).waitFor();
  await page.getByRole('dialog').getByRole('textbox', { name: 'Subject' }).fill('   ');
  await page.getByRole('dialog').getByRole('textbox', { name: 'Description' }).fill('Test details');
  await page.getByRole('dialog').getByRole('button', { name: 'Create Ticket' }).click();
  await page.getByText('Enter both a subject and a description.').waitFor();
  assert.equal(createdTicketPosts, 0);
  await page.getByRole('dialog').getByRole('textbox', { name: 'Subject' }).fill('New desk request');
  await page.getByRole('dialog').getByRole('button', { name: 'Create Ticket' }).click();
  await page.getByRole('heading', { name: 'New desk request' }).waitFor();
  assert.equal(createdTicketPosts, 1);
  assert.equal(runPosts, 0);
  await page.reload({ waitUntil: 'networkidle' });
  assert.equal(await page.locator('.ticket-table tbody tr').count(), 4);
  console.log('PASS: new-ticket validation, creation, immediate display, and refresh persistence (mocked API)');

  await page.getByRole('button', { name: 'Select ticket 101' }).click();
  await page.getByRole('heading', { name: 'Bulldog tee' }).waitFor();
  await page.getByRole('button', { name: 'Select ticket 102' }).click();
  await page.getByRole('heading', { name: 'Rent due' }).waitFor();
  await page.getByText('Recorded history · 1 events').waitFor();
  assert.ok(ticketHistoryRequests > 0);
  assert.equal(await page.locator('.agent-module .status--idle').count(), 5);
  assert.match(await page.locator('.agent-module').filter({ hasText: 'Facilities' }).innerText(), /History · mcp tool call/i);
  console.log('PASS: ticket selection, filtered history, and idle status distinct from participation');

  await page.locator('.detail-section').getByRole('button', { name: 'Run Ticket' }).click();
  await page.getByRole('button', { name: 'Running...' }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Running...' }).isDisabled(), true);
  await page.getByText('Rent requires human approval.').waitFor();
  assert.equal(runPosts, 1);
  console.log('PASS: run state and duplicate submission prevention');

  await page.getByRole('button', { name: 'Agent Activity' }).click();
  await page.getByText('check_lease_and_rent').first().waitFor();
  await page.locator('.event__summary').first().click();
  await page.getByText('rent_amount').waitFor();
  console.log('PASS: real event fields, activity filters, expanded details');

  await page.getByRole('button', { name: 'Approvals', exact: true }).click();
  await page.locator('.workspace').getByRole('button', { name: 'Approve' }).click();
  await page.getByRole('dialog', { name: 'Confirm payment' }).waitFor();
  assert.equal(approvalPosts, 0);
  await page.getByRole('dialog').getByRole('textbox', { name: 'Your name' }).fill('Test Human');
  await page.getByRole('dialog').getByRole('button', { name: 'Confirm payment' }).click();
  await page.getByText('$1,000.00').first().waitFor();
  assert.equal(approvalPosts, 1);
  console.log('PASS: approval confirmation and cash refresh, using mocked backend');

  await page.getByRole('button', { name: 'Reset Shop' }).click();
  await page.getByRole('dialog', { name: 'Reset shop data' }).waitFor();
  assert.equal(resetPosts, 0);
  assert.equal(await page.getByRole('dialog').getByRole('button', { name: 'Reset Shop' }).isDisabled(), true);
  await page.getByRole('dialog').getByRole('textbox', { name: 'Type RESET to confirm' }).fill('RESET');
  assert.equal(await page.getByRole('dialog').getByRole('button', { name: 'Reset Shop' }).isEnabled(), true);
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();
  assert.equal(resetPosts, 0);
  console.log('PASS: reset confirmation, no reset request issued');

  for (const width of [320, 390, 768, 1024]) {
    await page.setViewportSize({ width, height: 844 });
    await page.getByRole('button', { name: 'Overview' }).click();
    const measured = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
    assert.ok(measured.scroll <= measured.client, `Overflow at ${width}px: ${JSON.stringify(measured)}`);
    if (width === 390) await page.screenshot({ path: '/tmp/hw5-dashboard-mobile.png', fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: '/tmp/hw5-dashboard-desktop.png', fullPage: true });
  assert.deepEqual(pageErrors, []);
  console.log('PASS: mobile width, desktop rendering, no console errors');
} finally {
  await browser.close();
}
