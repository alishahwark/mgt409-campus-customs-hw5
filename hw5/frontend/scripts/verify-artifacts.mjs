import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { chromium } from '@playwright/test';

const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const page = await browser.newPage();

try {
  await page.goto(new URL('../../output/resolved_board.html', import.meta.url).href);
  assert.equal(await page.locator('figure img').count(), 3);
  const images = await page.locator('figure img').evaluateAll(items =>
    items.map(item => ({ loaded: item.complete && item.naturalWidth > 0, src: item.getAttribute('src') }))
  );
  assert.ok(images.every(item => item.loaded), JSON.stringify(images));
  console.log('PASS: offline resolved_board.html loads three real relative PNG files');

  await page.goto(new URL('../../output/desk_tickets.html', import.meta.url).href);
  assert.equal(await page.getByRole('tab').count(), 5);
  for (const id of ['101', '102', '103', 'cash', 'reflection']) {
    await page.locator(`#tab-${id}`).click();
    assert.equal(await page.locator(`#tab-${id}`).getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator(`#panel-${id}`).isVisible(), true);
  }
  for (const id of [101, 102, 103]) {
    assert.ok((await page.locator(`#panel-${id} .actual-report`).innerText()).length > 100);
  }
  const promptLog = readFileSync(new URL('../../AI_prompts.md', import.meta.url), 'utf8');
  for (const [id, next] of [[101, 'TICKET 102'], [102, 'TICKET 103'], [103, 'IMPLEMENTATION INSTRUCTIONS']]) {
    const start = promptLog.indexOf(`> TICKET ${id} —`);
    const end = promptLog.indexOf(`> ${next}`, start + 1);
    assert.ok(start >= 0 && end > start, `Problem 6 expected prompt ${id} is available`);
    const promptPlan = promptLog.slice(promptLog.indexOf('> First agent:', start), end)
      .split('\n').map(line => line.replace(/^> ?/, '')).join('\n').trim();
    const displayedPlan = (await page.locator(`#panel-${id} .expected-plan`).textContent()).trim();
    assert.equal(displayedPlan, promptPlan, `Expected plan ${id} is byte-for-byte preserved`);
  }
  assert.match(await page.locator('#panel-cash').innerText(), /\$3,400\.00/);
  assert.match(await page.locator('#panel-cash').innerText(), /\$160\.00/);
  console.log('PASS: offline desk_tickets.html has five functional tabs, exact Expected plans, actual results, and cash reconciliation');
} finally {
  await browser.close();
}
