import { describe, it, expect } from "vitest";
import {
  normalizeCartItems,
  computeCartTotal,
  generateOrderMessage,
  getContactUrl,
} from "./cartOrderMessage";

describe("normalizeCartItems", () => {
  it("utilise le prix normal quand pas de prix promo", () => {
    const result = normalizeCartItems([{ id: 1, name: "Robe", price: 100, quantity: 2 }]);
    expect(result[0].unit_price).toBe(100);
    expect(result[0].qty).toBe(2);
  });

  it("utilise le prix promo quand il est inférieur au prix normal", () => {
    const result = normalizeCartItems([{ id: 1, name: "Robe", price: 100, promo_price: 70 }]);
    expect(result[0].unit_price).toBe(70);
  });

  it("ignore le prix promo s'il n'est pas inférieur au prix normal (garde-fou anti-erreur d'affichage)", () => {
    const result = normalizeCartItems([{ id: 1, name: "Robe", price: 100, promo_price: 120 }]);
    expect(result[0].unit_price).toBe(100);
  });

  it("applique une quantité par défaut de 1 si absente", () => {
    const result = normalizeCartItems([{ id: 1, name: "Robe", price: 50 }]);
    expect(result[0].qty).toBe(1);
  });

  it("retourne un tableau vide pour une entrée null/undefined (garde-fou)", () => {
    expect(normalizeCartItems(null)).toEqual([]);
    expect(normalizeCartItems(undefined)).toEqual([]);
  });
});

describe("computeCartTotal", () => {
  it("calcule la somme correcte de plusieurs lignes", () => {
    const items = [
      { unit_price: 10, qty: 2 },
      { unit_price: 5, qty: 3 },
    ];
    expect(computeCartTotal(items)).toBe(35);
  });

  it("retourne 0 pour un panier vide", () => {
    expect(computeCartTotal([])).toBe(0);
  });
});

describe("generateOrderMessage — le message envoyé au marchand via WhatsApp", () => {
  const baseArgs = {
    effectiveItems: [{ name: "Robe", qty: 2, unit_price: 50 }],
    customerName: "",
    customerPhone: "",
    appliedPromotions: [],
    couponCode: "",
    effectiveDiscount: 0,
    effectiveTotal: 100,
  };

  it("inclut le total correct dans le message", () => {
    const msg = generateOrderMessage(baseArgs);
    expect(msg).toContain("100.000 DT");
  });

  it("calcule correctement le total de chaque ligne produit (prix × quantité)", () => {
    const msg = generateOrderMessage({
      ...baseArgs,
      effectiveItems: [{ name: "Chaussures", qty: 3, unit_price: 33.5 }],
    });
    expect(msg).toContain("Chaussures x3 = 100.500 DT");
  });

  it("inclut le nom et le téléphone client s'ils sont fournis", () => {
    const msg = generateOrderMessage({ ...baseArgs, customerName: "Amira", customerPhone: "+21600000000" });
    expect(msg).toContain("Amira");
    expect(msg).toContain("+21600000000");
  });

  it("omet nom/téléphone quand absents (pas de 'undefined' dans le message)", () => {
    const msg = generateOrderMessage(baseArgs);
    expect(msg).not.toContain("undefined");
    expect(msg).not.toContain("Nom:");
  });

  it("affiche la remise uniquement si elle est positive", () => {
    const withDiscount = generateOrderMessage({ ...baseArgs, effectiveDiscount: 15 });
    expect(withDiscount).toContain("Remise:* -15.000 DT");

    const withoutDiscount = generateOrderMessage(baseArgs);
    expect(withoutDiscount).not.toContain("Remise:");
  });

  it("liste les promotions appliquées avec leur montant", () => {
    const msg = generateOrderMessage({
      ...baseArgs,
      appliedPromotions: [{ promotion_name: "Soldes été", discount_amount: 10 }],
    });
    expect(msg).toContain("Soldes été");
    expect(msg).toContain("-10.000 DT");
  });

  it("affiche 'appliquée' pour une promotion à 0 DT plutôt que '-0.000 DT' (lisibilité)", () => {
    const msg = generateOrderMessage({
      ...baseArgs,
      appliedPromotions: [{ promotion_name: "Livraison offerte", discount_amount: 0 }],
    });
    expect(msg).toContain("Livraison offerte");
    expect(msg).not.toContain("-0.000 DT");
  });

  it("inclut le code promo saisi", () => {
    const msg = generateOrderMessage({ ...baseArgs, couponCode: "ETE2026" });
    expect(msg).toContain("ETE2026");
  });
});

describe("getContactUrl — les liens envoyés au client pour contacter le marchand", () => {
  const store = {
    whatsapp_phone: "+216 20 000 000",
    messenger_page_id: "12345",
    instagram_handle: "@maboutique",
    tiktok_handle: "@maboutique",
  };

  it("nettoie le numéro WhatsApp de tous les caractères non-numériques", () => {
    const url = getContactUrl("whatsapp", store, "test");
    expect(url).toBe("https://wa.me/21620000000?text=test");
  });

  it("encode correctement le message dans l'URL WhatsApp", () => {
    const url = getContactUrl("whatsapp", store, "Total: 100 DT & remise");
    expect(url).toContain(encodeURIComponent("Total: 100 DT & remise"));
  });

  it("retourne null pour Messenger si le store n'a pas de page configurée", () => {
    expect(getContactUrl("messenger", { ...store, messenger_page_id: null }, "test")).toBeNull();
  });

  it("retire le @ du handle Instagram dans l'URL générée", () => {
    const url = getContactUrl("instagram", store, "test");
    expect(url).toBe("https://instagram.com/maboutique");
  });

  it("retourne null pour un canal inconnu", () => {
    expect(getContactUrl("email", store, "test")).toBeNull();
  });

  it("ne plante pas si store est undefined (garde-fou)", () => {
    expect(() => getContactUrl("whatsapp", undefined, "test")).not.toThrow();
    expect(getContactUrl("messenger", undefined, "test")).toBeNull();
  });
});
