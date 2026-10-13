import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

// Capture the real, unmodified Vite dashboard against the live backend.
// No API routes, run results, statuses, or screenshots are mocked or injected.
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });

try {
  await page.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' });
  await page.locator('.ticket-table tbody tr').first().waitFor();
  assert.equal(await page.locator('.ticket-table tbody tr').count(), 3);
  await page.getByText('$160.00').first().waitFor();
  await page.getByText('SYSTEM ONLINE').waitFor();

  for (const [ticketId, heading] of [[101, 'Bulldog tee'], [102, 'Rent due'], [103, 'Bulk hoodie discount']]) {
    await page.getByRole('button', { name: `Select ticket ${ticketId}` }).click();
    await page.getByRole('heading', { name: heading, exact: true }).waitFor();
    await page.getByRole('button', { name: 'Desk Resolved' }).waitFor();
    if (ticketId !== 102) await page.getByLabel('Recorded internal desk resolution').waitFor();
    const file = fileURLToPath(new URL(`../../output/ticket-${ticketId}.png`, import.meta.url));
    await page.screenshot({ path: file, fullPage: true, animations: 'disabled' });
    console.log(`Captured real dashboard ticket ${ticketId}: ${file}`);
  }
  assert.deepEqual(errors, []);
} finally {
  await browser.close();
}
