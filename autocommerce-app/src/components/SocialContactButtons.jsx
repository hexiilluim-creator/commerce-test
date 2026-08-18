import React from 'react';

/**
 * SocialContactButtons — Boutons de contact direct via les réseaux sociaux
 * Supporte : WhatsApp, Messenger, Instagram, TikTok
 */
export default function SocialContactButtons({ store, message = '' }) {
  if (!store) return null;

  // Fonction pour construire les URLs de contact
  const getContactUrl = (platform) => {
    const msg = encodeURIComponent(message || `Bonjour ${store.name}! Je découvre votre boutique 👋`);
    
    switch (platform) {
      case 'whatsapp':
        return `https://wa.me/${(store.whatsapp_phone || '').replace(/\D/g, '')}?text=${msg}`;
      
      case 'messenger':
        // Format: https://m.me/{PAGE_ID}?ref={REF}
        return store.messenger_page_id 
          ? `https://m.me/${store.messenger_page_id}?ref=storefront`
          : null;
      
      case 'instagram':
        // Format: https://instagram.com/{USERNAME}
        return store.instagram_handle
          ? `https://instagram.com/${store.instagram_handle.replace('@', '')}`
          : null;
      
      case 'tiktok':
        // Format: https://tiktok.com/@{USERNAME}
        return store.tiktok_handle
          ? `https://tiktok.com/@${store.tiktok_handle.replace('@', '')}`
          : null;
      
      default:
        return null;
    }
  };

  // Définir les boutons disponibles
  const buttons = [
    {
      id: 'whatsapp',
      label: 'WhatsApp',
      icon: '💬',
      color: '#25D366',
      bgColor: '#E8F5E9',
      textColor: '#1B5E20',
      enabled: !!store.whatsapp_phone,
    },
    {
      id: 'messenger',
      label: 'Messenger',
      icon: '💭',
      color: '#0084FF',
      bgColor: '#E3F2FD',
      textColor: '#0D47A1',
      enabled: !!store.messenger_page_id,
    },
    {
      id: 'instagram',
      label: 'Instagram',
      icon: '📷',
      color: '#E4405F',
      bgColor: '#FCE4EC',
      textColor: '#880E4F',
      enabled: !!store.instagram_handle,
    },
    {
      id: 'tiktok',
      label: 'TikTok',
      icon: '🎵',
      color: '#000000',
      bgColor: '#F5F5F5',
      textColor: '#000000',
      enabled: !!store.tiktok_handle,
    },
  ];

  const enabledButtons = buttons.filter(btn => btn.enabled);

  if (enabledButtons.length === 0) {
    return null;
  }

  return (
    <div className="flex flex-wrap gap-3">
      {enabledButtons.map((btn) => {
        const url = getContactUrl(btn.id);
        if (!url) return null;

        return (
          <a
            key={btn.id}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 rounded-xl font-semibold text-sm transition-all hover:shadow-lg active:scale-95"
            style={{
              backgroundColor: btn.bgColor,
              color: btn.textColor,
              border: `2px solid ${btn.color}`,
            }}
          >
            <span className="text-lg">{btn.icon}</span>
            <span>{btn.label}</span>
          </a>
        );
      })}
    </div>
  );
}
