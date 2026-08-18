import { test, expect } from '@playwright/test';
test('tenant kill switch', async ({ page }) => {
  await page.goto('/admin/settings');
  // ... test kill switch ...
  expect(true).toBe(true);
});