import { describe, it, expect, beforeEach } from "vitest";
import {
  setActiveStorefrontStore,
  getActiveStorefrontStore,
  getStorefrontCartKey,
  loadStorefrontCart,
  saveStorefrontCart,
  clearStorefrontCart,
} from "./storefrontCart";

describe("storefrontCart", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("génère une clé de panier distincte par store (isolation multi-tenant)", () => {
    expect(getStorefrontCartKey(1)).not.toBe(getStorefrontCartKey(2));
    expect(getStorefrontCartKey(1)).toBe("autocommerce:storefront:cart:1");
  });

  it("retourne un panier vide quand rien n'est sauvegardé", () => {
    expect(loadStorefrontCart(42)).toEqual([]);
  });

  it("sauvegarde puis recharge le panier pour le bon store", () => {
    const items = [{ productId: 1, qty: 2 }];
    saveStorefrontCart(1, items);
    expect(loadStorefrontCart(1)).toEqual(items);
  });

  it("isole les paniers entre deux stores différents", () => {
    saveStorefrontCart(1, [{ productId: 1, qty: 2 }]);
    saveStorefrontCart(2, [{ productId: 9, qty: 1 }]);
    expect(loadStorefrontCart(1)).toEqual([{ productId: 1, qty: 2 }]);
    expect(loadStorefrontCart(2)).toEqual([{ productId: 9, qty: 1 }]);
  });

  it("retourne un tableau vide si le JSON stocké est corrompu (pas de crash)", () => {
    window.localStorage.setItem(getStorefrontCartKey(1), "{ceci n'est pas du JSON");
    expect(loadStorefrontCart(1)).toEqual([]);
  });

  it("retourne un tableau vide si la valeur stockée n'est pas un tableau", () => {
    window.localStorage.setItem(getStorefrontCartKey(1), JSON.stringify({ not: "an array" }));
    expect(loadStorefrontCart(1)).toEqual([]);
  });

  it("ignore les valeurs non-tableau passées à saveStorefrontCart (garde-fou)", () => {
    // @ts-expect-error — test délibéré d'une entrée invalide
    saveStorefrontCart(1, "not-an-array");
    expect(loadStorefrontCart(1)).toEqual([]);
  });

  it("met à jour le store actif lors d'une sauvegarde de panier", () => {
    saveStorefrontCart(7, [{ productId: 1, qty: 1 }]);
    expect(getActiveStorefrontStore()).toBe("7");
  });

  it("vide le panier d'un store sans toucher aux autres", () => {
    saveStorefrontCart(1, [{ productId: 1, qty: 1 }]);
    saveStorefrontCart(2, [{ productId: 2, qty: 1 }]);
    clearStorefrontCart(1);
    expect(loadStorefrontCart(1)).toEqual([]);
    expect(loadStorefrontCart(2)).toEqual([{ productId: 2, qty: 1 }]);
  });

  it("ne fait rien si storeId est absent (garde-fou)", () => {
    expect(() => saveStorefrontCart(null, [{ productId: 1 }])).not.toThrow();
    expect(() => setActiveStorefrontStore(null)).not.toThrow();
  });
});
