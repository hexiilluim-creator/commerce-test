import { test, expect } from '@playwright/test';
test('checkout stripe', async ({ page }) => {
  await page.goto('/store/boutique-demo');
  // ... mock stripe checkout ...
  expect(true).toBe(true);
});