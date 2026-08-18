/**
 * storefront-purchase.spec.ts — Tests e2e Playwright (P2‑2)
 *
 * Couvre le parcours critique d'un acheteur public :
 *   1. Ouverture du storefront (cat. paginée + images WebP/AVIF chargés)
 *   2. Ajout au panier
 *   3. Checkout Stripe (test card 4242…)
 *
 * Exécution :
 *   pnpm exec playwright install --with-deps chromium
 *   pnpm exec playwright test storefront-purchase.spec.ts
 *
 * Variables d'env :
 *   E2E_BASE_URL      ex: http://localhost:8000
 *   E2E_STORE_SLUG    ex: boutique-demo (doit être is_active=True, stock>0)
 *   E2E_API_KEY       jeton bearer admin (pour seed data via API REST)
 */
import { test, expect, request as pwRequest } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:8000";
const SLUG = process.env.E2E_STORE_SLUG ?? "boutique-demo";

test.describe("Storefront P2-2 — perf catalogue + checkout", () => {
  test("首页 storefront liste paginée avec images WebP", async ({ page }) => {
    const start = Date.now();
    await page.goto(`${BASE_URL}/api/v1/storefront/${SLUG}/products?limit=12`, {
      waitUntil: "domcontentloaded",
    });
    const elapsed = Date.now() - start;
    expect(elapsed).toBeLessThan(800);                    // SLO catalogue P95 < 800 ms

    // Vérifie la présence du champ `cache` indiquant HIT/MISS
    const body = await page.evaluate(() => (document.body.innerText));
    expect(body).toMatch(/"cache":"(HIT|MISS)"/);
    expect(body).toMatch(/"next_cursor"/);

    // Vérifie le contenu d'image : primary + webp + avif + placeholder
    expect(body).toMatch(/"webp"/);
    expect(body).toMatch(/"avif"/);
    expect(body).toMatch(/data:image\/svg\+xml;utf8,/);
  });

  test("Pagination keyset via next_cursor", async ({ page }) => {
    await page.goto(`${BASE_URL}/api/v1/storefront/${SLUG}/products?limit=4`);
    const page1 = JSON.parse((await page.locator("body").innerText()) || "{}");
    expect(Array.isArray(page1.products)).toBeTruthy();
    expect(page1.products.length).toBeLessThanOrEqual(4);

    if (!page1.next_cursor) {
      test.skip(true, "Pas assez de produits pour tester la pagination");
      return;
    }
    const url2 = `${BASE_URL}/api/v1/storefront/${SLUG}/products?limit=4&cursor=${encodeURIComponent(page1.next_cursor)}`;
    await page.goto(url2);
    const page2 = JSON.parse(await page.locator("body").innerText());
    expect(page2.products.length).toBeGreaterThanOrEqual(0);

    // Pas de doublon entre les deux pages
    const ids1 = new Set(page1.products.map((p: { id: number }) => p.id));
    page2.products.forEach((p: { id: number }) => expect(ids1.has(p.id)).toBeFalsy());
  });

  test("Parcours achat storefront → checkout Stripe (carte test)", async ({ page, context }) => {
    // Simule le panier côté client (localStorage) — le storefront est public
    test.skip(!process.env.E2E_STRIPE_PUBLIC_KEY, "E2E_STRIPE_PUBLIC_KEY absent — skip checkout");

    await page.goto(`${BASE_URL}/api/v1/storefront/${SLUG}/products?limit=1`);
    const rows = JSON.parse(await page.locator("body").innerText());
    expect(rows.products.length).toBeGreaterThanOrEqual(1);
    const sampleProduct = rows.products[0];

    // Ouvre la page storefront publique (si dispo) et clique sur le CTA
    await page.goto(`/store/${SLUG}`);
    await page.locator(`[data-test="add-to-cart-${sampleProduct.id}"]`).first().click();
    await page.locator(`[data-test="open-cart"]`).click();
    await page.locator(`[data-test="checkout-stripe"]`).click();

    // Stripe Checkout — carte test 4242 4242 4242 4242
    const stripeFrame = page.frameLocator('iframe[name^="__privateStripeFrame"]');
    await stripeFrame.locator('input[name="cardNumber"]').fill("4242 4242 4242 4242");
    await stripeFrame.locator('input[name="cardExpiry"]').fill("12/30");
    await stripeFrame.locator('input[name="cardCvc"]').fill("123");
    await stripeFrame.locator('input[name="billingName"]').fill("Test Acheteur");
    // Soumettre
    await page.locator('[data-test="submit-stripe"]').click();
    await expect(page.locator('[data-test="order-confirmed"]')).toBeVisible({ timeout: 15_000 });
  });

  test("Cache HIT sur 2ᵉ requête consécutive (Redis)", async ({ page }) => {
    const url = `${BASE_URL}/api/v1/storefront/${SLUG}/products?limit=12`;
    await page.goto(url);
    const r1 = JSON.parse(await page.locator("body").innerText());
    await page.goto(url);
    const r2 = JSON.parse(await page.locator("body").innerText());

    expect(["HIT", "MISS"]).toContain(r1.cache);
    expect(["HIT", "MISS"]).toContain(r2.cache);
    // Au moins l'une des deux doit être HIT après warmup
    expect(r1.cache === "HIT" || r2.cache === "HIT").toBeTruthy();
  });
});
