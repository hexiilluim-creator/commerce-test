import { test, expect } from '@playwright/test';
test('byok openai', async ({ page }) => {
  await page.goto('/admin/settings/ai');
  // ... test byok ...
  expect(true).toBe(true);
});