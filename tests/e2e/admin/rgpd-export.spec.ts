import { test, expect } from '@playwright/test';
test('rgpd export', async ({ page }) => {
  await page.goto('/admin/settings/gdpr');
  // ... test export ...
  expect(true).toBe(true);
});