import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiGet } from '../api';
// AUDIT FIX: QR code généré localement — package 'qrcode' (npm install qrcode).
// Remplace l'appel à api.qrserver.com (dépendance externe, RGPD, indisponibilité offline).
import QRCode from 'qrcode';

/* ══════════════════════════════════════════════════════════
   MyStorefront — Page marchande "Ma Vitrine Publique"
   Accessible depuis la sidebar, toujours disponible.
   
   Fonctionnalités :
   - URL publique toujours affichée (indépendante du score)
   - QR Code généré côté client (Canvas API, 0 dépendance)
   - Aperçu live iframe de la boutique publique
   - Checklist de complétude avec liens d'action
   - Partage WhatsApp / copier / ouvrir
══════════════════════════════════════════════════════════ */

// ─── QR Code generator (local, package 'qrcode') ─────────────────────────────
// AUDIT FIX: Génération locale via Canvas — aucune donnée envoyée à un service tiers.
// Nécessite : npm install qrcode  (+ @types/qrcode pour TypeScript)
function QRCodeCard({ url, storeName }) {
  const [copied, setCopied] = useState(false);
  const [qrError, setQrError] = useState(false);
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!url) return;
    setQrError(false);
    const canvas = canvasRef.current;
    if (!canvas) return;
    QRCode.toCanvas(canvas, url, {
      width: 160,
      margin: 1,
      color: { dark: '#000000ff', light: '#ffffffff' },
    }).catch(() => setQrError(true));
  }, [url]);

  const handleCopy = () => {
    navigator.clipboard?.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => {
      const el = document.createElement('textarea');
      el.value = url;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const handleDownloadQR = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dataURL = canvas.toDataURL('image/png');
    const a = document.createElement('a');
    a.href = dataURL;
    a.download = `qr-boutique-${storeName || 'store'}.png`;
    a.click();
  };

  return (
    <div className="premium-card p-6 flex flex-col items-center gap-4">
      <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider self-start">📲 QR Code boutique</h3>
      <div className="p-3 premium-card shadow-inner">
        {!qrError ? (
          <canvas
            ref={canvasRef}
            width={160}
            height={160}
            className="rounded-lg"
            aria-label="QR Code boutique"
          />
        ) : (
          <div className="w-40 h-40 flex items-center justify-center bg-gray-50 rounded-lg text-center">
            <div>
              <div className="text-3xl mb-2">📷</div>
              <p className="text-xs text-gray-400">QR Code<br/>indisponible</p>
            </div>
          </div>
        )}
      </div>
      <p className="text-xs text-gray-400 text-center">Imprimez ce code et collez-le sur votre vitrine physique !</p>
      <div className="flex gap-2 w-full">
        <button
          onClick={handleDownloadQR}
          className="flex-1 py-2 px-3 text-xs font-semibold rounded-xl border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
        >
          ⬇️ Télécharger
        </button>
        <button
          onClick={handleCopy}
          className={`flex-1 py-2 px-3 text-xs font-semibold rounded-xl transition-all ${copied ? 'bg-green-500 text-white' : 'bg-indigo-50 text-indigo-600 hover:bg-indigo-100'}`}
        >
          {copied ? '✅ Copié !' : '📋 Copier lien'}
        </button>
      </div>
    </div>
  );
}

// ─── URL Card ─────────────────────────────────────────────────────────────────
function PublicUrlCard({ url, slug }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard?.writeText(url).catch(() => {
      const el = document.createElement('textarea');
      el.value = url;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    });
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const waShare = `https://wa.me/?text=${encodeURIComponent(`🛍️ Découvrez ma boutique en ligne !\n${url}`)}`;

  return (
    <div className="bg-gradient-to-br from-indigo-600 to-purple-700 rounded-2xl p-6 text-white shadow-lg shadow-indigo-200">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xl">🔗</span>
        <span className="text-sm font-bold text-indigo-200 uppercase tracking-wider">Lien public de votre boutique</span>
      </div>

      {/* URL display */}
      <div className="bg-white/10 backdrop-blur rounded-xl px-4 py-3 mb-4 font-mono text-sm break-all text-white/90 border border-white/20">
        {url}
      </div>

      {/* Actions */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={handleCopy}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-bold transition-all ${
            copied
              ? 'bg-green-400 text-white'
              : 'bg-white text-indigo-700 hover:bg-indigo-50'
          }`}
        >
          {copied ? '✅ Copié !' : '📋 Copier'}
        </button>
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-4 py-2.5 bg-white/15 hover:bg-white/25 rounded-xl text-sm font-bold text-white border border-white/25 transition-all"
        >
          👁️ Ouvrir
        </a>
        <a
          href={waShare}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-4 py-2.5 bg-green-500 hover:bg-green-400 rounded-xl text-sm font-bold text-white transition-all"
        >
          💬 Partager via WhatsApp
        </a>
      </div>
    </div>
  );
}

// ─── Completeness Checklist ───────────────────────────────────────────────────
const ACTION_LINKS = {
  name:                  '/settings/store',
  whatsapp_phone:        '/settings/store',
  language:              '/settings/store',
  logo_url:              '/settings/store',
  description:           '/settings/store',
  support_email:         '/settings/store',
  ai_agent_prompt:       '/settings/ai',
  products:              '/products',
  whatsapp_configured:   '/settings/whatsapp',
};

function CompletenessChecklist({ completeness, navigate }) {
  if (!completeness) return null;
  const { score, is_online, checks } = completeness;

  const items = Object.entries(checks || {}).map(([key, val]) => ({
    key,
    ...val,
    link: ACTION_LINKS[key] || '/settings/store',
  }));

  const required  = items.filter(i => i.type === 'required');
  const recommended = items.filter(i => i.type === 'recommended');

  return (
    <div className="premium-card p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider">
          {is_online ? '✅ Boutique en ligne' : '⚠️ Complétude boutique'}
        </h3>
        <div className="flex items-center gap-2">
          <span className={`text-2xl font-black ${score === 100 ? 'text-green-600' : score >= 60 ? 'text-amber-500' : 'text-red-500'}`}>
            {score}%
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden mb-5">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{
            width: `${score}%`,
            background: score === 100 ? '#22c55e' : score >= 60 ? '#f59e0b' : '#ef4444',
          }}
        />
      </div>

      {/* Required */}
      <div className="mb-4">
        <p className="text-xs font-bold text-gray-400 uppercase mb-2">Obligatoire</p>
        <div className="space-y-2">
          {required.map(item => (
            <div key={item.key} className="flex items-center justify-between py-2 px-3 rounded-xl bg-gray-50">
              <div className="flex items-center gap-2">
                <span className={`text-sm ${item.ok ? 'text-green-500' : 'text-red-400'}`}>
                  {item.ok ? '✅' : '❌'}
                </span>
                <span className={`text-sm ${item.ok ? 'text-gray-700' : 'text-gray-500'}`}>{item.label}</span>
              </div>
              {!item.ok && (
                <button
                  onClick={() => navigate(item.link)}
                  className="text-xs font-bold text-indigo-600 hover:text-indigo-800"
                >
                  Configurer →
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Recommended */}
      <div>
        <p className="text-xs font-bold text-gray-400 uppercase mb-2">Recommandé</p>
        <div className="space-y-2">
          {recommended.map(item => (
            <div key={item.key} className="flex items-center justify-between py-2 px-3 rounded-xl bg-gray-50">
              <div className="flex items-center gap-2">
                <span className={`text-sm ${item.ok ? 'text-green-500' : 'text-amber-400'}`}>
                  {item.ok ? '✅' : '💡'}
                </span>
                <span className={`text-sm ${item.ok ? 'text-gray-700' : 'text-gray-500'}`}>{item.label}</span>
              </div>
              {!item.ok && (
                <button
                  onClick={() => navigate(item.link)}
                  className="text-xs font-bold text-indigo-600 hover:text-indigo-800"
                >
                  Améliorer →
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Preview iframe ───────────────────────────────────────────────────────────
function PreviewPanel({ url, slug }) {
  const [previewMode, setPreviewMode] = useState('mobile'); // 'mobile' | 'desktop'
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <div className="premium-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider">👁️ Aperçu live</h3>
        <div className="flex items-center gap-2">
          <div className="flex bg-gray-100 rounded-lg p-0.5">
            <button
              onClick={() => setPreviewMode('mobile')}
              className={`px-3 py-1 text-xs font-bold rounded-md transition-all ${previewMode === 'mobile' ? 'bg-white shadow text-gray-800' : 'text-gray-400'}`}
            >
              📱 Mobile
            </button>
            <button
              onClick={() => setPreviewMode('desktop')}
              className={`px-3 py-1 text-xs font-bold rounded-md transition-all ${previewMode === 'desktop' ? 'bg-white shadow text-gray-800' : 'text-gray-400'}`}
            >
              🖥️ Bureau
            </button>
          </div>
          <button
            onClick={() => setReloadKey(k => k + 1)}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 text-sm"
            title="Rafraîchir l'aperçu"
          >
            🔄
          </button>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 text-sm"
            title="Ouvrir dans un nouvel onglet"
          >
            ↗️
          </a>
        </div>
      </div>

      {/* Preview area */}
      <div
        className="flex items-start justify-center py-6 px-4 bg-gray-50 transition-all duration-300"
        style={{ minHeight: 520 }}
      >
        <div
          className="relative bg-white rounded-2xl shadow-xl overflow-hidden transition-all duration-300"
          style={
            previewMode === 'mobile'
              ? { width: 375, height: 640, border: '6px solid #1f2937', borderRadius: 28 }
              : { width: '100%', maxWidth: 780, height: 520, border: '1px solid #e5e7eb', borderRadius: 12 }
          }
        >
          <iframe
            key={reloadKey}
            src={url}
            title="Aperçu boutique publique"
            className="w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin allow-forms"
          />
        </div>
      </div>
    </div>
  );
}

// ─── Share tips section ───────────────────────────────────────────────────────
function ShareTips({ url, storeName }) {
  const tips = [
    {
      icon: '📸',
      title: 'Story Instagram / TikTok',
      desc: 'Ajoutez votre lien dans votre bio et partagez-le en story avec un autocollant lien.',
      color: 'bg-pink-50 border-pink-100',
    },
    {
      icon: '💬',
      title: 'Groupe WhatsApp',
      desc: 'Envoyez votre lien de boutique dans vos groupes de clients et communautés.',
      color: 'bg-green-50 border-green-100',
    },
    {
      icon: '🖨️',
      title: 'Flyer & carte de visite',
      desc: 'Imprimez le QR code et collez-le sur vos emballages, affiches ou cartes de visite.',
      color: 'bg-blue-50 border-blue-100',
    },
    {
      icon: '🔵',
      title: 'Page Facebook',
      desc: 'Ajoutez votre lien de boutique dans la description de votre page Facebook.',
      color: 'bg-indigo-50 border-indigo-100',
    },
  ];

  return (
    <div className="premium-card p-6">
      <h3 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-4">🚀 Comment partager votre boutique</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {tips.map((tip, i) => (
          <div key={i} className={`rounded-xl border p-4 ${tip.color}`}>
            <div className="flex items-start gap-3">
              <span className="text-xl mt-0.5">{tip.icon}</span>
              <div>
                <p className="text-sm font-bold text-gray-800 mb-1">{tip.title}</p>
                <p className="text-xs text-gray-500 leading-relaxed">{tip.desc}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function MyStorefront() {
  const navigate = useNavigate();
  const [completeness, setCompleteness] = useState(null);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState(null);
  const [activeTab, setActiveTab]       = useState('overview'); // 'overview' | 'preview' | 'share'

  const publicUrl = completeness
    ? (completeness.public_url || `${window.location.origin}/store/${completeness.slug}`)
    : null;

  const fetchCompleteness = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await apiGet('/settings/store/completeness');
      setCompleteness(data);
    } catch (e) {
      setError('Impossible de charger les informations de la boutique.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCompleteness();
  }, [fetchCompleteness]);

  // ── Loading ──────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600 mx-auto mb-3" />
          <p className="text-sm text-gray-500">Chargement de votre vitrine…</p>
        </div>
      </div>
    );
  }

  // ── Error ────────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="text-center max-w-sm">
          <div className="text-4xl mb-3">⚠️</div>
          <p className="text-sm text-gray-600 mb-4">{error}</p>
          <button
            onClick={fetchCompleteness}
            className="px-4 py-2 bg-indigo-600 text-white rounded-xl text-sm font-semibold"
          >
            Réessayer
          </button>
        </div>
      </div>
    );
  }

  const tabs = [
    { id: 'overview', label: '🏪 Aperçu' },
    { id: 'preview',  label: '👁️ Prévisualisation' },
    { id: 'share',    label: '📤 Partage' },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-16">

      {/* ── Page header ── */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-xl lg:text-2xl font-bold text-gray-900">
            🏪 Ma Vitrine Publique
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {completeness?.store_name || 'Votre boutique'} — visible par tous vos clients
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`px-3 py-1.5 rounded-full text-xs font-bold flex items-center gap-1.5 ${
            completeness?.is_online
              ? 'bg-green-100 text-green-700 border border-green-200'
              : 'bg-amber-100 text-amber-700 border border-amber-200'
          }`}>
            <span className={`w-2 h-2 rounded-full ${completeness?.is_online ? 'bg-green-500 animate-pulse' : 'bg-amber-400'}`} />
            {completeness?.is_online ? 'En ligne' : 'Configuration requise'}
          </div>
        </div>
      </div>

      {/* ── Public URL (ALWAYS shown) ── */}
      {publicUrl && (
        <PublicUrlCard url={publicUrl} slug={completeness?.slug} />
      )}

      {/* ── Tabs ── */}
      <div className="flex bg-gray-100 rounded-xl p-1 gap-1">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 py-2 text-xs lg:text-sm font-semibold rounded-lg transition-all ${
              activeTab === tab.id ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── Tab: Overview ── */}
      {activeTab === 'overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Left: completeness */}
          <CompletenessChecklist completeness={completeness} navigate={navigate} />

          {/* Right: QR code */}
          {publicUrl && (
            <QRCodeCard url={publicUrl} storeName={completeness?.store_name} />
          )}
        </div>
      )}

      {/* ── Tab: Preview ── */}
      {activeTab === 'preview' && publicUrl && (
        <PreviewPanel url={publicUrl} slug={completeness?.slug} />
      )}

      {/* ── Tab: Share ── */}
      {activeTab === 'share' && publicUrl && (
        <div className="space-y-6">
          <QRCodeCard url={publicUrl} storeName={completeness?.store_name} />
          <ShareTips url={publicUrl} storeName={completeness?.store_name} />
        </div>
      )}

      {/* ── CTA si incomplète ── */}
      {!completeness?.is_online && completeness?.required_missing?.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 flex items-start gap-4">
          <span className="text-2xl mt-0.5">💡</span>
          <div className="flex-1">
            <p className="text-sm font-bold text-amber-800 mb-1">
              Votre boutique n&apos;est pas encore en ligne
            </p>
            <p className="text-xs text-amber-700 mb-3">
              Complétez les {completeness.required_missing.length} élément(s) requis pour que vos clients puissent voir votre boutique.
            </p>
            <div className="flex flex-wrap gap-2">
              {completeness.required_missing.map(item => (
                <button
                  key={item.key}
                  onClick={() => navigate(ACTION_LINKS[item.key] || '/settings/store')}
                  className="text-xs font-bold px-3 py-1.5 bg-amber-100 hover:bg-amber-200 text-amber-800 rounded-lg transition-colors border border-amber-300"
                >
                  + {item.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <p className="text-xs text-gray-300 text-center pb-4">
        Lien toujours accessible : votre vitrine est visible même si la configuration est incomplète.
      </p>
    </div>
  );
}
