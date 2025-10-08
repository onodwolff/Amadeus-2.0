import { expect, test } from '@playwright/test';

test.describe('Dashboard smoke test', () => {
  test('renders the command center shell', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Launch backtest bot' })).toBeVisible();
  });
});
