import React, { useState, useCallback, useMemo } from 'react';

/**
 * SocialChannelIntegration Component
 * Gère l'envoi de commandes groupées via WhatsApp, Messenger, Instagram et TikTok
 * Optimisé pour chaque plateforme avec formatage spécifique
 */
import { formatMoney } from '../utils/currency';

export default function SocialChannelIntegration({ store, cartItems, cartTotal }) {
  const [selectedChannel, setSelectedChannel] = useState('whatsapp');
  const [isLoading, setIsLoading] = useState(false);

  // Formateurs de message spécifiques à chaque plateforme
  const messageFormatters = useMemo(() => ({
    whatsapp: (items, total) => {
      const header = `🛍️ *COMMANDE GROUPÉE* — ${store?.name || 'AutoCommerce'}\n\n`;
      const itemsList = items
        .map((item, idx) => {
          const price = item.promo_price && item.promo_price < item.price ? item.promo_price : item.price;
          const itemTotal = price * item.qty;
          const discount = item.promo_price && item.promo_price < item.price
            ? ` _(Promo: -${Math.round((1 - item.promo_price / item.price) * 100)}%)_`
            : '';
          return `${idx + 1}. *${item.name}*\n   Quantité: ${item.qty} × ${formatMoney(price, store, 'fr')}${discount}\n   Sous-total: ${formatMoney(itemTotal, store, 'fr')}\n`;
        })
        .join('\n');
      const footer = `\n━━━━━━━━━━━━━━━━━━━━\n*TOTAL: ${formatMoney(total, store, 'fr')}*\n━━━━━━━━━━━━━━━━━━━━\n\n📍 Livraison: À confirmer\n💳 Paiement: À confirmer\n⏰ Délai: À convenir\n\nMerci pour votre commande! 🙏`;
      return header + itemsList + footer;
    },
    messenger: (items, total) => {
      const header = `🛍️ COMMANDE GROUPÉE — ${store?.name || 'AutoCommerce'}\n\n`;
      const itemsList = items
        .map((item, idx) => {
          const price = item.promo_price && item.promo_price < item.price ? item.promo_price : item.price;
          const itemTotal = price * item.qty;
          return `${idx + 1}. ${item.name}\n   Quantité: ${item.qty} × ${formatMoney(price, store, 'fr')} = ${formatMoney(itemTotal, store, 'fr')}\n`;
        })
        .join('\n');
      const footer = `\n━━━━━━━━━━━━━━━━━━━━\nTOTAL: ${formatMoney(total, store, 'fr')}\n━━━━━━━━━━━━━━━━━━━━\n\n📍 Livraison: À confirmer\n💳 Paiement: À confirmer\n\nMerci! 🙏`;
      return header + itemsList + footer;
    },
    instagram: (items, total) => {
      const header = `🛍️ COMMANDE GROUPÉE\n${store?.name || 'AutoCommerce'}\n\n`;
      const itemsList = items
        .map((item, idx) => {
          const price = item.promo_price && item.promo_price < item.price ? item.promo_price : item.price;
          return `${idx + 1}. ${item.name} ×${item.qty} — ${formatMoney(price * item.qty, store, 'fr')}`;
        })
        .join('\n');
      const footer = `\n━━━━━━━━━━━━━━━━━━\nTOTAL: ${formatMoney(total, store, 'fr')}\n━━━━━━━━━━━━━━━━━━\n\n📍 Livraison: À confirmer\n💳 Paiement: À confirmer\n\nMerci! 🙏`;
      return header + itemsList + footer;
    },
    tiktok: (items, total) => {
      const header = `🛍️ COMMANDE — ${store?.name || 'AutoCommerce'}\n`;
      const itemsList = items
        .map((item) => {
          const price = item.promo_price && item.promo_price < item.price ? item.promo_price : item.price;
          return `• ${item.name} ×${item.qty} = ${formatMoney(price * item.qty, store, 'fr')}`;
        })
        .join('\n');
      const footer = `\n━━━━━━━━━━━━━━━━━━\nTOTAL: ${formatMoney(total, store, 'fr')}\n━━━━━━━━━━━━━━━━━━`;
      return header + itemsList + footer;
    },
  }), [store]);

  // Générer le message pour le canal sélectionné
  const generateMessage = useCallback(() => {
    const formatter = messageFormatters[selectedChannel];
    return formatter ? formatter(cartItems, cartTotal) : '';
  }, [selectedChannel, cartItems, cartTotal, messageFormatters]);

  // Envoyer via le canal spécifié
  const handleSendOrder = useCallback(async (channel) => {
    setIsLoading(true);
    const message = generateMessage();

    try {
      let url = '';
      switch (channel) {
        case 'whatsapp':
          const waPhone = (store?.whatsapp_phone || '').replace(/\D/g, '');
          url = `https://wa.me/${waPhone}?text=${encodeURIComponent(message)}`;
          break;
        case 'messenger':
          url = `https://m.me/${store?.facebook_page_id || ''}`;
          break;
        case 'instagram':
          url = `https://instagram.com/${store?.instagram_username || ''}`;
          break;
        case 'tiktok':
          url = `https://tiktok.com/@${store?.tiktok_username || ''}`;
          break;
        default:
          return;
      }

      // Enregistrer la tentative d'envoi
      if (window.fetch) {
        fetch('/api/v1/social/order-sent', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            channel,
            items_count: cartItems.length,
            total: cartTotal,
            message_preview: message.substring(0, 100),
          }),
        }).catch(() => {}); // Best-effort logging
      }

      // Ouvrir le lien
      window.open(url, '_blank');
    } finally {
      setIsLoading(false);
    }
  }, [generateMessage, store, cartItems, cartTotal]);

  const channels = [
    { id: 'whatsapp', label: 'WhatsApp', icon: '💬', color: '#25d366', emoji: '📱' },
    { id: 'messenger', label: 'Messenger', icon: '📘', color: '#0084ff', emoji: '💙' },
    { id: 'instagram', label: 'Instagram', icon: '📸', color: '#e1306c', emoji: '💗' },
    { id: 'tiktok', label: 'TikTok', icon: '🎵', color: '#000000', emoji: '🎬' },
  ];

  return (
    <div style={{
      background: 'white',
      borderRadius: '16px',
      padding: '24px',
      border: '1.5px solid #e5e7eb',
      marginTop: '24px',
    }}>
      {/* Titre */}
      <h3 style={{
        fontSize: '16px',
        fontWeight: '700',
        color: '#0c0c0c',
        marginBottom: '16px',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
      }}>
        🌐 Envoyer votre commande
      </h3>

      {/* Sélection du canal */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))',
        gap: '12px',
        marginBottom: '20px',
      }}>
        {channels.map((channel) => (
          <button
            key={channel.id}
            onClick={() => setSelectedChannel(channel.id)}
            style={{
              padding: '12px',
              borderRadius: '12px',
              border: selectedChannel === channel.id ? `2.5px solid ${channel.color}` : '1.5px solid #e5e7eb',
              background: selectedChannel === channel.id ? `${channel.color}15` : 'white',
              color: selectedChannel === channel.id ? channel.color : '#6a6a6a',
              fontWeight: '600',
              fontSize: '13px',
              cursor: 'pointer',
              transition: 'all 0.2s',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '6px',
            }}
            onMouseEnter={(e) => {
              if (selectedChannel !== channel.id) {
                e.target.style.borderColor = channel.color;
                e.target.style.background = `${channel.color}08`;
              }
            }}
            onMouseLeave={(e) => {
              if (selectedChannel !== channel.id) {
                e.target.style.borderColor = '#e5e7eb';
                e.target.style.background = 'white';
              }
            }}
          >
            <span style={{ fontSize: '20px' }}>{channel.icon}</span>
            {channel.label}
          </button>
        ))}
      </div>

      {/* Aperçu du message */}
      <div style={{
        background: '#f9fafb',
        borderRadius: '12px',
        padding: '16px',
        marginBottom: '16px',
        maxHeight: '200px',
        overflowY: 'auto',
        fontSize: '12px',
        color: '#6a6a6a',
        fontFamily: 'monospace',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {generateMessage()}
      </div>

      {/* Bouton d'envoi */}
      <button
        onClick={() => handleSendOrder(selectedChannel)}
        disabled={isLoading || cartItems.length === 0}
        style={{
          width: '100%',
          padding: '14px',
          borderRadius: '12px',
          background: channels.find(c => c.id === selectedChannel)?.color || '#1d4ed8',
          color: 'white',
          border: 'none',
          fontWeight: '700',
          fontSize: '14px',
          cursor: isLoading ? 'not-allowed' : 'pointer',
          opacity: isLoading || cartItems.length === 0 ? 0.6 : 1,
          transition: 'all 0.2s',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '8px',
        }}
        onMouseEnter={(e) => {
          if (!isLoading && cartItems.length > 0) {
            e.target.style.opacity = '0.9';
            e.target.style.transform = 'scale(1.02)';
          }
        }}
        onMouseLeave={(e) => {
          e.target.style.opacity = '1';
          e.target.style.transform = 'scale(1)';
        }}
      >
        {isLoading ? (
          <>
            ⏳ Envoi en cours...
          </>
        ) : (
          <>
            {channels.find(c => c.id === selectedChannel)?.icon} Envoyer via {channels.find(c => c.id === selectedChannel)?.label}
          </>
        )}
      </button>

      {/* Note informative */}
      <p style={{
        fontSize: '11px',
        color: '#9ca3af',
        marginTop: '12px',
        textAlign: 'center',
      }}>
        ℹ️ Vous serez redirigé vers l'application pour confirmer l'envoi
      </p>
    </div>
  );
}
