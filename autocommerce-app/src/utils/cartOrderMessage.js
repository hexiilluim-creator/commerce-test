/**
 * src/utils/cartOrderMessage.js — logique pure extraite de OptimizedCartV2.jsx
 * (P1.14 — amélioration de la couverture de tests frontend).
 *
 * Ces fonctions gèrent de l'argent réel affiché au client et envoyé dans le
 * message de commande WhatsApp/Messenger/Instagram/TikTok — un bug ici
 * signifie un mauvais total montré au client ou envoyé au marchand.
 * Extraites du composant pour être testables sans rendu React.
 */
import { formatMoney } from './currency';

const formatOrderAmount = (value, store) => store
  ? formatMoney(value, store, 'fr')
  : `${Number(value || 0).toFixed(3)} DT`;

/**
 * Normalise les items bruts du panier : choisit le prix promo si inférieur
 * au prix normal, applique les valeurs par défaut (quantité, catégorie).
 */
export function normalizeCartItems(items) {
  return (items || []).map((item) => {
    const price = item.promo_price && item.promo_price < item.price ? item.promo_price : item.price;
    return {
      product_id: item.id,
      name: item.name,
      qty: item.quantity || 1,
      unit_price: price,
      category: item.category,
      tax_category: item.tax_category || item.category,
      is_tax_exempt: !!item.is_tax_exempt,
    };
  });
}

/** Somme des lignes (prix unitaire × quantité) d'items normalisés. */
export function computeCartTotal(normalizedItems) {
  return (normalizedItems || []).reduce((sum, item) => sum + (item.unit_price * item.qty), 0);
}

/**
 * Construit le message texte de commande (WhatsApp/Messenger/...).
 * Toute erreur ici envoie un mauvais prix/total au client ou au marchand.
 */
export function generateOrderMessage({
  effectiveItems,
  customerName,
  customerPhone,
  appliedPromotions,
  couponCode,
  effectiveDiscount,
  effectiveTotal,
  store,
}) {
  let msg = `🛒 *Nouvelle Commande*\n\n`;

  if (customerName) msg += `👤 *Nom:* ${customerName}\n`;
  if (customerPhone) msg += `📱 *Téléphone:* ${customerPhone}\n`;

  msg += `\n*Produits:*\n`;
  (effectiveItems || []).forEach((item, idx) => {
    const lineTotal = Number(item.unit_price || 0) * Number(item.qty || 1);
    msg += `${idx + 1}. ${item.name} x${item.qty || 1} = ${formatOrderAmount(lineTotal, store)}\n`;
  });

  if (appliedPromotions?.length) {
    msg += `\n*Promotions appliquées:*\n`;
    appliedPromotions.forEach((promo) => {
      const amount = Number(promo.discount_amount || 0);
      msg += `- ${promo.promotion_name}${amount !== 0 ? ` (-${formatOrderAmount(amount, store)})` : ''}\n`;
    });
  }

  if (couponCode && couponCode.trim()) {
    msg += `\n🎟️ *Code promo:* ${couponCode.trim()}\n`;
  }

  if (effectiveDiscount > 0) {
    msg += `💸 *Remise:* -${formatOrderAmount(Number(effectiveDiscount), store)}\n`;
  }

  msg += `\n💰 *Total:* ${formatOrderAmount(Number(effectiveTotal), store)}\n`;
  msg += `\n✅ Merci de confirmer cette commande !`;
  return msg;
}

/**
 * Construit l'URL de contact pour un canal donné (WhatsApp/Messenger/
 * Instagram/TikTok). Renvoie null si le canal n'est pas configuré pour ce
 * store — un lien mal formé enverrait le client vers un compte inexistant.
 */
export function getContactUrl(channel, store, message) {
  const msg = encodeURIComponent(message);

  switch (channel) {
    case 'whatsapp':
      return `https://wa.me/${(store?.whatsapp_phone || '').replace(/\D/g, '')}?text=${msg}`;
    case 'messenger':
      return store?.messenger_page_id
        ? `https://m.me/${store.messenger_page_id}?ref=order`
        : null;
    case 'instagram':
      return store?.instagram_handle
        ? `https://instagram.com/${store.instagram_handle.replace('@', '')}`
        : null;
    case 'tiktok':
      return store?.tiktok_handle
        ? `https://tiktok.com/@${store.tiktok_handle.replace('@', '')}`
        : null;
    default:
      return null;
  }
}
