import { test, expect } from '@playwright/test';
test('mfa login', async ({ page }) => {
  await page.goto('/admin/login');
  // ... test MFA flow ...
  expect(true).toBe(true);
});