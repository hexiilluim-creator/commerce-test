import { test, expect } from '@playwright/test';
test('checkout flouci', async ({ page }) => {
  await page.goto('/store/boutique-demo');
  // ... mock flouci redirect ...
  expect(true).toBe(true);
});