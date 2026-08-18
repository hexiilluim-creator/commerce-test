import React, { useState } from 'react';

/**
 * FloatingContactBar — Barre de contact flottante en bas de la page
 * Affiche les boutons de contact de manière compacte et accessible
 */
export default function FloatingContactBar({ store }) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!store) return null;

  // Vérifier quels canaux sont disponibles
  const availableChannels = [
    store.whatsapp_phone && 'whatsapp',
    store.messenger_page_id && 'messenger',
    store.instagram_handle && 'instagram',
    store.tiktok_handle && 'tiktok',
  ].filter(Boolean);

  if (availableChannels.length === 0) {
    return null;
  }

  // Construire les URLs
  const getUrl = (channel) => {
    const msg = encodeURIComponent(`Bonjour ${store.name}! Je découvre votre boutique 👋`);
    
    switch (channel) {
      case 'whatsapp':
        return `https://wa.me/${(store.whatsapp_phone || '').replace(/\D/g, '')}?text=${msg}`;
      case 'messenger':
        return store.messenger_page_id ? `https://m.me/${store.messenger_page_id}` : null;
      case 'instagram':
        return store.instagram_handle ? `https://instagram.com/${store.instagram_handle.replace('@', '')}` : null;
      case 'tiktok':
        return store.tiktok_handle ? `https://tiktok.com/@${store.tiktok_handle.replace('@', '')}` : null;
      default:
        return null;
    }
  };

  const channelInfo = {
    whatsapp: { label: 'WhatsApp', icon: '💬', color: '#25D366' },
    messenger: { label: 'Messenger', icon: '💭', color: '#0084FF' },
    instagram: { label: 'Instagram', icon: '📷', color: '#E4405F' },
    tiktok: { label: 'TikTok', icon: '🎵', color: '#000000' },
  };

  return (
    <div className="fixed bottom-4 right-4 z-40">
      {/* Bouton principal (toggle) */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-14 h-14 rounded-full shadow-lg hover:shadow-xl transition-all active:scale-95 flex items-center justify-center text-2xl"
        style={{
          backgroundColor: '#111827',
          color: '#fff',
        }}
      >
        {isExpanded ? '✕' : '💬'}
      </button>

      {/* Menu déroulant */}
      {isExpanded && (
        <div className="absolute bottom-20 right-0 bg-white rounded-2xl shadow-2xl p-4 min-w-max border border-gray-100">
          <p className="text-xs font-semibold text-gray-600 mb-3 px-2">Nous contacter :</p>
          <div className="flex flex-col gap-2">
            {availableChannels.map((channel) => {
              const info = channelInfo[channel];
              const url = getUrl(channel);
              if (!url) return null;

              return (
                <a
                  key={channel}
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-3 px-4 py-3 rounded-lg hover:bg-gray-50 transition-colors text-sm font-medium"
                >
                  <span className="text-xl">{info.icon}</span>
                  <span className="text-gray-700">{info.label}</span>
                </a>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
