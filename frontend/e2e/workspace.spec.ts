import { test, expect, type Page } from '@playwright/test'

async function importFixture(page: Page) {
  await page
    .getByLabel('GitHub repository URL')
    .fill('https://github.com/patchwork-ai/browser-fixture')
  await page.getByRole('button', { name: 'Add repository' }).click()
  await expect(page.getByLabel('Selected repository')).toContainText(
    'browser-fixture',
  )
}

test.beforeEach(async ({ request }) => {
  expect((await request.post('/api/__test/reset')).ok()).toBeTruthy()
})

test('empty state, loading, API failure and recovery', async ({ page }) => {
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/repositories', async (route) => {
    await gate
    await route.continue()
  })
  await page.goto('/')
  await expect(page.getByText('Loading repositories…')).toBeVisible()
  release()
  await expect(page.getByLabel('Selected repository')).toContainText(
    'No repositories',
  )
  await expect(
    page.getByRole('button', { name: 'Investigate snapshot' }),
  ).toBeDisabled()
  await page.unroute('**/api/repositories')
  await page.route('**/api/repositories', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ error: { message: 'Controlled API outage' } }),
    }),
  )
  await page.reload()
  await expect(page.getByText('Controlled API outage')).toBeVisible()
  await page.unroute('**/api/repositories')
  await page.reload()
  await importFixture(page)
  await expect(
    page.getByRole('button', { name: 'subject.py', exact: false }).first(),
  ).toBeVisible()
  await page
    .getByRole('button', { name: 'test_subject.py', exact: true })
    .focus()
  await page.keyboard.press('Enter')
  await expect(
    page.getByText('from packaging.version import Version', { exact: false }),
  ).toBeVisible()
})

test('import, search, investigate, review, approve and real Docker verification', async ({
  page,
  request,
}, info) => {
  await page.goto('/')
  await importFixture(page)
  await page.getByPlaceholder('Search code, symbols, and paths').fill('repair')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(
    page.getByText('subject.py:1', { exact: false }).first(),
  ).toBeVisible()
  await page.getByText('subject.py:1', { exact: false }).first().click()
  await expect(
    page.getByText('return a - b', { exact: false }).first(),
  ).toBeVisible()
  await page
    .getByLabel('Describe the bug or question')
    .fill('Arithmetic fixture bug: repair should add')
  await page.getByRole('button', { name: 'Investigate snapshot' }).click()
  await expect(
    page.getByText('Investigation running. Status refreshes automatically.'),
  ).toBeVisible()
  await expect(page.getByText('COMPLETED', { exact: true })).toBeVisible()
  await page
    .getByRole('button', { name: 'Propose evidence-backed patch' })
    .click()
  await page.getByRole('link', { name: 'Open patch review' }).click()
  const patches = await (await request.get('/api/patches')).json()
  const patchId = patches.items[0].id
  expect(
    (
      await request.post(`/api/patches/${patchId}/verifications`, { data: {} })
    ).status(),
  ).toBe(409)
  await expect(
    page.getByRole('button', { name: 'Verify', exact: true }),
  ).toHaveCount(0)
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await page.getByRole('button', { name: 'Verify', exact: true }).click()
  await expect(page.getByText('IMPROVED', { exact: true })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText('pass (2/2)', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByText('IMPROVED', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Choose investigation')).toContainText(
    'completed',
  )
  await page.screenshot({
    path: `test-results/${info.project.name}-workflow.png`,
    fullPage: true,
  })
})

test('cancellation is persisted across browser refresh', async ({
  page,
  request,
}) => {
  await page.goto('/')
  await importFixture(page)
  await page
    .getByLabel('Describe the bug or question')
    .fill('wait for cancellation')
  await page.getByRole('button', { name: 'Investigate snapshot' }).click()
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByText('CANCELLED', { exact: true })).toBeVisible()
  const investigations = await (await request.get('/api/investigations')).json()
  const id = investigations.items[0].id
  const first = await (
    await request.post(`/api/investigations/${id}/cancel`)
  ).json()
  expect(
    await (await request.post(`/api/investigations/${id}/cancel`)).json(),
  ).toEqual(first)
  await page.reload()
  await expect(page.getByText('CANCELLED', { exact: true })).toBeVisible()
})

test('active Docker verification can be cancelled before results exist', async ({
  page,
  request,
}) => {
  const { patch_id: patchId } = await (
    await request.post('/api/__test/slow-patch')
  ).json()
  expect(
    (
      await request.post(`/api/patches/${patchId}/approve`, {
        data: {
          decision: 'approve',
          reviewer: 'browser-fixture',
          reason: 'Explicit controlled fixture approval',
        },
      })
    ).ok(),
  ).toBeTruthy()
  const command = "python -m unittest discover -v -p 'fixture_test_*.py'"
  const { verification } = await (
    await request.post(`/api/patches/${patchId}/verifications`, {
      data: { baseline_command: command, patched_command: command },
    })
  ).json()
  await page.goto('/')
  await page
    .getByRole('button', { name: 'Cancel verification', exact: true })
    .click()
  await expect(page.getByText('CANCELLED', { exact: true })).toBeVisible()
  const url = `/api/verifications/${verification.id}/cancel`
  const first = await (await request.post(url)).json()
  expect(await (await request.post(url)).json()).toEqual(first)
  expect(first.verification.comparison).toBeNull()
  await page.reload()
  await expect(page.getByText('CANCELLED', { exact: true })).toBeVisible()
})
