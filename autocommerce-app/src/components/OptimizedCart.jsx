import React, { useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { formatMoney } from '../utils/currency';

/**
 * OptimizedCart Component
 * Panier multi-produits optimisé pour WhatsApp, Messenger, Instagram et TikTok
 * Permet de grouper plusieurs produits et d'envoyer un récapitulatif formaté
 */
export default function OptimizedCart({ store, onClose, onOrderSubmit }) {
  const { t } = useTranslation();
  const [cartItems, setCartItems] = useState([]);
  const [showCart, setShowCart] = useState(false);

  // Ajouter un produit au panier
  const addToCart = useCallback((product, qty = 1) => {
    setCartItems((prev) => {
      const existing = prev.find((item) => item.id === product.id);
      if (existing) {
        return prev.map((item) =>
          item.id === product.id
            ? { ...item, qty: Math.min(item.qty + qty, product.stock_qty) }
            : item
        );
      }
      return [...prev, { ...product, qty: Math.min(qty, product.stock_qty) }];
    });
  }, []);

  // Retirer un produit du panier
  const removeFromCart = useCallback((productId) => {
    setCartItems((prev) => prev.filter((item) => item.id !== productId));
  }, []);

  // Mettre à jour la quantité
  const updateQty = useCallback((productId, qty) => {
    setCartItems((prev) =>
      prev.map((item) =>
        item.id === productId
          ? { ...item, qty: Math.max(1, Math.min(qty, item.stock_qty)) }
          : item
      )
    );
  }, []);

  // Calculs du panier
  const cartStats = useMemo(() => {
    const total = cartItems.reduce((sum, item) => sum + (item.price * item.qty), 0);
    const promoTotal = cartItems.reduce((sum, item) => {
      const price = item.promo_price && item.promo_price < item.price ? item.promo_price : item.price;
      return sum + (price * item.qty);
    }, 0);
    const savings = total - promoTotal;

    return {
      itemCount: cartItems.length,
      unitCount: cartItems.reduce((sum, item) => sum + item.qty, 0),
      subtotal: total,
      total: promoTotal,
      savings,
      hasSavings: savings > 0,
    };
  }, [cartItems]);

  // Générer le message formaté pour WhatsApp/Messenger/IG/TikTok
  const generateOrderMessage = useCallback((platform = 'whatsapp') => {
    if (cartItems.length === 0) return '';

    const header = `🛍️ *COMMANDE GROUPÉE* — ${store?.name || 'AutoCommerce'}\n`;
    const items = cartItems
      .map((item, idx) => {
        const price = item.promo_price && item.promo_price < item.price ? item.promo_price : item.price;
        const itemTotal = price * item.qty;
        const promo = item.promo_price && item.promo_price < item.price
          ? ` (Promo: -${Math.round((1 - item.promo_price / item.price) * 100)}%)`
          : '';
        return `${idx + 1}. *${item.name}* × ${item.qty}\n   ${formatMoney(price, store, 'fr')}/unité${promo}\n   Sous-total: ${formatMoney(itemTotal, store, 'fr')}`;
      })
      .join('\n\n');

    const footer = `\n\n━━━━━━━━━━━━━━━━━━━━\n*TOTAL: ${formatMoney(cartStats.total, store, 'fr')}*${
      cartStats.hasSavings ? `\n✓ Économie: ${formatMoney(cartStats.savings, store, 'fr')}` : ''
    }\n━━━━━━━━━━━━━━━━━━━━\n\n📍 Livraison: À confirmer\n💳 Paiement: À confirmer`;

    return header + items + footer;
  }, [cartItems, store, cartStats]);

  // Envoyer la commande via le canal spécifié
  const handleSendOrder = useCallback((platform) => {
    if (cartItems.length === 0) return;

    const message = generateOrderMessage(platform);
    const phone = (store?.whatsapp_phone || '').replace(/\D/g, '');

    let url = '';
    switch (platform) {
      case 'whatsapp':
        url = `https://wa.me/${phone}?text=${encodeURIComponent(message)}`;
        break;
      case 'messenger':
        // Messenger n'a pas de deep link direct, on ouvre juste la page
        url = `https://m.me/${store?.facebook_page_id || ''}`;
        break;
      case 'instagram':
        // Instagram DM via URL scheme (limité)
        url = `https://instagram.com/${store?.instagram_username || ''}`;
        break;
      case 'tiktok':
        // TikTok n'a pas de DM direct, on ouvre le profil
        url = `https://tiktok.com/@${store?.tiktok_username || ''}`;
        break;
      default:
        return;
    }

    if (onOrderSubmit) {
      onOrderSubmit({ platform, message, items: cartItems, total: cartStats.total });
    }

    window.open(url, '_blank');
  }, [cartItems, store, cartStats, generateOrderMessage, onOrderSubmit]);

  const fmt = (n) => formatMoney(n, store, 'fr');

  if (!showCart && cartItems.length === 0) return null;

  return (
    <>
      {/* Bouton flottant du panier */}
      {cartItems.length > 0 && !showCart && (
        <button
          onClick={() => setShowCart(true)}
          style={{
            position: 'fixed',
            bottom: '24px',
            right: '24px',
            width: '64px',
            height: '64px',
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #1d4ed8, #2563eb)',
            color: 'white',
            border: 'none',
            cursor: 'pointer',
            fontSize: '24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 8px 24px rgba(29, 78, 216, 0.4)',
            zIndex: 40,
            animation: 'pulse 2s infinite',
          }}
          title={`${cartStats.unitCount} article(s) dans le panier`}
        >
          <span style={{ position: 'relative' }}>
            🛒
            <span
              style={{
                position: 'absolute',
                top: '-8px',
                right: '-8px',
                background: '#ef4444',
                color: 'white',
                width: '24px',
                height: '24px',
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '12px',
                fontWeight: '700',
              }}
            >
              {cartStats.unitCount}
            </span>
          </span>
        </button>
      )}

      {/* Modal du panier */}
      {showCart && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 50,
            background: 'rgba(0,0,0,0.6)',
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'center',
          }}
          onClick={(e) => e.target === e.currentTarget && setShowCart(false)}
        >
          <div
            style={{
              background: 'white',
              width: '100%',
              maxWidth: '500px',
              borderRadius: '24px 24px 0 0',
              maxHeight: '90vh',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 -8px 32px rgba(0,0,0,0.15)',
              animation: 'slideUp 0.3s ease',
            }}
          >
            {/* Header */}
            <div
              style={{
                padding: '20px 24px',
                borderBottom: '1px solid #e5e7eb',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <h2 style={{ fontSize: '20px', fontWeight: '700', color: '#0c0c0c', margin: 0 }}>
                🛒 Votre Panier ({cartStats.unitCount})
              </h2>
              <button
                onClick={() => setShowCart(false)}
                style={{
                  background: 'none',
                  border: 'none',
                  fontSize: '24px',
                  cursor: 'pointer',
                  color: '#6a6a6a',
                }}
              >
                ✕
              </button>
            </div>

            {/* Contenu du panier */}
            <div
              style={{
                flex: 1,
                overflowY: 'auto',
                padding: '16px 24px',
              }}
            >
              {cartItems.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px 20px', color: '#6a6a6a' }}>
                  <p style={{ fontSize: '16px', marginBottom: '8px' }}>Votre panier est vide</p>
                  <p style={{ fontSize: '13px' }}>Ajoutez des produits pour commencer</p>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {cartItems.map((item) => {
                    const price = item.promo_price && item.promo_price < item.price ? item.promo_price : item.price;
                    const itemTotal = price * item.qty;
                    return (
                      <div
                        key={item.id}
                        style={{
                          display: 'flex',
                          gap: '12px',
                          padding: '12px',
                          background: '#f9fafb',
                          borderRadius: '12px',
                          border: '1px solid #e5e7eb',
                        }}
                      >
                        {/* Image */}
                        {item.image_url && (
                          <img
                            src={item.image_url}
                            alt={item.name}
                            style={{
                              width: '60px',
                              height: '60px',
                              borderRadius: '8px',
                              objectFit: 'cover',
                            }}
                          />
                        )}

                        {/* Infos */}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <h4 style={{
                            fontSize: '13px',
                            fontWeight: '700',
                            color: '#0c0c0c',
                            margin: '0 0 4px',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}>
                            {item.name}
                          </h4>
                          <p style={{
                            fontSize: '12px',
                            color: '#6a6a6a',
                            margin: '0',
                          }}>
                            {fmt(price)} × {item.qty} = <strong>{fmt(itemTotal)}</strong>
                          </p>
                        </div>

                        {/* Contrôles quantité */}
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                        }}>
                          <button
                            onClick={() => updateQty(item.id, item.qty - 1)}
                            style={{
                              width: '28px',
                              height: '28px',
                              borderRadius: '6px',
                              border: '1px solid #e5e7eb',
                              background: 'white',
                              cursor: 'pointer',
                              fontSize: '14px',
                              fontWeight: '700',
                            }}
                          >
                            −
                          </button>
                          <span style={{
                            width: '24px',
                            textAlign: 'center',
                            fontSize: '13px',
                            fontWeight: '700',
                          }}>
                            {item.qty}
                          </span>
                          <button
                            onClick={() => updateQty(item.id, item.qty + 1)}
                            style={{
                              width: '28px',
                              height: '28px',
                              borderRadius: '6px',
                              border: '1px solid #e5e7eb',
                              background: 'white',
                              cursor: 'pointer',
                              fontSize: '14px',
                              fontWeight: '700',
                            }}
                          >
                            +
                          </button>
                          <button
                            onClick={() => removeFromCart(item.id)}
                            style={{
                              width: '28px',
                              height: '28px',
                              borderRadius: '6px',
                              background: '#fef2f2',
                              border: '1px solid #fecaca',
                              color: '#dc2626',
                              cursor: 'pointer',
                              fontSize: '14px',
                              fontWeight: '700',
                            }}
                          >
                            🗑️
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Footer avec totaux et CTA */}
            {cartItems.length > 0 && (
              <div style={{
                padding: '20px 24px',
                borderTop: '1px solid #e5e7eb',
                background: '#f9fafb',
              }}>
                {/* Résumé */}
                <div style={{ marginBottom: '16px' }}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      fontSize: '13px',
                      color: '#6a6a6a',
                      marginBottom: '8px',
                    }}
                  >
                    <span>Sous-total:</span>
                    <span>{fmt(cartStats.subtotal)}</span>
                  </div>
                  {cartStats.hasSavings && (
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        fontSize: '13px',
                        color: '#10b981',
                        fontWeight: '600',
                        marginBottom: '8px',
                      }}
                    >
                      <span>✓ Économie:</span>
                      <span>-{fmt(cartStats.savings)}</span>
                    </div>
                  )}
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      fontSize: '16px',
                      fontWeight: '700',
                      color: '#0c0c0c',
                      paddingTop: '8px',
                      borderTop: '1px solid #e5e7eb',
                    }}
                  >
                    <span>Total:</span>
                    <span>{fmt(cartStats.total)}</span>
                  </div>
                </div>

                {/* Boutons d'envoi */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  <button
                    onClick={() => handleSendOrder('whatsapp')}
                    style={{
                      padding: '12px',
                      borderRadius: '12px',
                      background: '#25d366',
                      color: 'white',
                      border: 'none',
                      fontWeight: '700',
                      fontSize: '13px',
                      cursor: 'pointer',
                      transition: 'all 0.2s',
                    }}
                    onMouseEnter={(e) => e.target.style.background = '#20ba5a'}
                    onMouseLeave={(e) => e.target.style.background = '#25d366'}
                  >
                    💬 WhatsApp
                  </button>
                  <button
                    onClick={() => handleSendOrder('messenger')}
                    style={{
                      padding: '12px',
                      borderRadius: '12px',
                      background: '#0084ff',
                      color: 'white',
                      border: 'none',
                      fontWeight: '700',
                      fontSize: '13px',
                      cursor: 'pointer',
                      transition: 'all 0.2s',
                    }}
                    onMouseEnter={(e) => e.target.style.background = '#0073e6'}
                    onMouseLeave={(e) => e.target.style.background = '#0084ff'}
                  >
                    📘 Messenger
                  </button>
                </div>

                {/* Options supplémentaires */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginTop: '12px' }}>
                  <button
                    onClick={() => handleSendOrder('instagram')}
                    style={{
                      padding: '12px',
                      borderRadius: '12px',
                      background: '#e1306c',
                      color: 'white',
                      border: 'none',
                      fontWeight: '700',
                      fontSize: '13px',
                      cursor: 'pointer',
                      transition: 'all 0.2s',
                    }}
                    onMouseEnter={(e) => e.target.style.background = '#c13584'}
                    onMouseLeave={(e) => e.target.style.background = '#e1306c'}
                  >
                    📸 Instagram
                  </button>
                  <button
                    onClick={() => handleSendOrder('tiktok')}
                    style={{
                      padding: '12px',
                      borderRadius: '12px',
                      background: '#000000',
                      color: 'white',
                      border: 'none',
                      fontWeight: '700',
                      fontSize: '13px',
                      cursor: 'pointer',
                      transition: 'all 0.2s',
                    }}
                    onMouseEnter={(e) => e.target.style.background = '#333333'}
                    onMouseLeave={(e) => e.target.style.background = '#000000'}
                  >
                    🎵 TikTok
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <style>{`
        @keyframes slideUp {
          from {
            transform: translateY(100%);
            opacity: 0;
          }
          to {
            transform: translateY(0);
            opacity: 1;
          }
        }
        @keyframes pulse {
          0%, 100% {
            transform: scale(1);
          }
          50% {
            transform: scale(1.05);
          }
        }
      `}</style>
    </>
  );
}
