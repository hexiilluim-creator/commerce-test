// src/pages/Settings.jsx — P1-C: Store settings, WhatsApp, Payments, Users
import React, { useEffect, useState } from 'react';
import { useStore } from '../context/StoreContext';
import { useConfirm } from '../context/ConfirmContext';
import StockSources from './StockSources';


const TABS = [
  { id: 'store', label: '🏪 Boutique' },
  { id: 'whatsapp', label: '💬 WhatsApp' },
  { id: 'payments', label: '💳 Paiements' },
  { id: 'users', label: '👥 Équipe' },
  { id: 'agent', label: '🤖 Agent IA' },
  { id: 'social', label: '📱 Réseaux sociaux' },
];

const PROVIDERS = ['stripe', 'flouci', 'clix', 'tnpay', 'cmi', 'aliapay', 'nexus', 'cash'];
const COUNTRY_OPTIONS = [
  ['TN', 'Tunisie', 'TND'], ['MA', 'Maroc', 'MAD'], ['DZ', 'Algérie', 'DZD'],
  ['FR', 'France', 'EUR'], ['DE', 'Allemagne', 'EUR'], ['IT', 'Italie', 'EUR'],
  ['ES', 'Espagne', 'EUR'], ['BE', 'Belgique', 'EUR'], ['US', 'États-Unis', 'USD'],
  ['CA', 'Canada', 'CAD'], ['GB', 'Royaume-Uni', 'GBP'], ['AE', 'Émirats arabes unis', 'AED'],
  ['SA', 'Arabie saoudite', 'SAR'], ['SN', 'Sénégal', 'XOF'], ['CI', 'Côte d’Ivoire', 'XOF'],
];
const CURRENCY_OPTIONS = ['TND', 'MAD', 'DZD', 'EUR', 'USD', 'CAD', 'GBP', 'AED', 'SAR', 'XOF'];

/* ─── CongratsModal ─────────────────────────────────────────────────────────── */
function CongratsModal({ store, onClose }) {
  const slug = store?.slug || 'ma-boutique';
  const publicUrl = `${window.location.origin}/store/${slug}`;

  return (
    <div style={{
      position:'fixed', inset:0, background:'rgba(0,0,0,0.85)', zIndex:9999,
      display:'flex', alignItems:'center', justifyContent:'center', padding:24,
    }} onClick={e => e.target===e.currentTarget && onClose()}>
      <div style={{
        background:'linear-gradient(135deg,#0d2015,#0a1a10)',
        border:'1px solid rgba(37,211,102,0.3)',
        borderRadius:24, padding:'40px 36px', maxWidth:480, width:'100%',
        textAlign:'center', boxShadow:'0 0 60px rgba(37,211,102,0.15)',
        animation:'fadeUp 0.4s ease',
      }}>
        {/* Confetti emoji animation */}
        <div style={{ fontSize:56, marginBottom:8, lineHeight:1 }}>🎉</div>
        <div style={{ fontSize:36, marginBottom:20 }}>✅</div>

        <h2 style={{ fontFamily:'Syne,sans-serif', fontWeight:800, fontSize:24, color:'#e8f5ec', marginBottom:10, lineHeight:1.2 }}>
          Félicitations ! 🎊
        </h2>
        <p style={{ fontSize:15, color:'#a8d4b4', lineHeight:1.7, marginBottom:6 }}>
          <strong style={{ color:'#25D366' }}>{store?.name || 'Votre magasin'}</strong> est désormais <strong style={{ color:'#25D366' }}>en ligne</strong> !
        </p>
        <p style={{ fontSize:13, color:'#7aab88', lineHeight:1.6, marginBottom:24 }}>
          Elle est visible et accessible par vos clients via le lien ci-dessous. Vous pouvez dès maintenant l'envoyer à vos clients pour plus d'interaction ! 🚀
        </p>

        {/* URL boutique */}
        <div style={{ background:'rgba(37,211,102,0.08)', border:'1px solid rgba(37,211,102,0.25)', borderRadius:14, padding:'14px 18px', marginBottom:20 }}>
          <div style={{ fontSize:11, color:'#7aab88', fontWeight:600, letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:6 }}>🔗 Lien de votre boutique</div>
          <div style={{ fontFamily:'monospace', fontSize:14, color:'#25D366', fontWeight:700, wordBreak:'break-all' }}>
            autocommerce/{slug}
          </div>
          <div style={{ fontSize:12, color:'#7aab88', marginTop:4 }}>{publicUrl}</div>
        </div>

        {/* Actions */}
        <div style={{ display:'flex', gap:12, justifyContent:'center', flexWrap:'wrap' }}>
          <button
            onClick={() => { navigator.clipboard?.writeText(publicUrl); }}
            style={{ background:'rgba(37,211,102,0.12)', border:'1px solid rgba(37,211,102,0.3)', color:'#25D366', borderRadius:12, padding:'11px 22px', fontSize:14, fontWeight:700, cursor:'pointer' }}
          >
            📋 Copier le lien
          </button>
          <a href={publicUrl} target="_blank" rel="noopener noreferrer"
            style={{ background:'#25D366', color:'#000', borderRadius:12, padding:'11px 22px', fontSize:14, fontWeight:700, textDecoration:'none', display:'inline-block' }}>
            👁️ Voir ma boutique
          </a>
        </div>

        <button onClick={onClose} style={{ marginTop:20, background:'none', border:'none', color:'#7aab88', fontSize:13, cursor:'pointer' }}>
          Fermer
        </button>
      </div>
    </div>
  );
}

/* ─── WhatsAppUpgradeWall ────────────────────────────────────────────────────── */
function WhatsAppUpgradeWall({ gate }) {
  const planLabels = {
    starter: 'Starter',
    business: 'Business',
    premium: 'Premium',
    pro_whatsapp: 'Pro WhatsApp',
    free: 'Gratuit',
  };
  const currentLabel = planLabels[gate?.plan_code] || gate?.plan_code || 'votre plan actuel';

  const FEATURES = [
    { icon: '💬', text: 'Conversations WhatsApp illimitées' },
    { icon: '🤖', text: 'Agent IA WhatsApp (réponses automatiques)' },
    { icon: '📱', text: 'Numéros multiples (multi-boutiques)' },
    { icon: '🔗', text: 'Intégration Meta Cloud API (webhook)' },
    { icon: '📦', text: 'Notifications commandes automatiques' },
    { icon: '⚡', text: '5 000 crédits IA/mois + recharges disponibles' },
  ];

  const handleUpgrade = () => {
    const section = document.getElementById('pricing');
    if (section) section.scrollIntoView({ behavior: 'smooth' });
    else window.location.href = '/#pricing';
  };

  return (
    <div style={{
      maxWidth: 680, margin: '0 auto',
      background: 'linear-gradient(135deg,#0d1f14,#0a1a10)',
      border: '1px solid rgba(37,211,102,0.2)',
      borderRadius: 24, padding: '48px 40px', textAlign: 'center',
      boxShadow: '0 8px 48px rgba(0,0,0,0.4)',
    }}>
      {/* Icon */}
      <div style={{ fontSize: 72, lineHeight: 1, marginBottom: 12 }}>💬</div>
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 6, background: 'rgba(37,211,102,0.1)',
        border: '1px solid rgba(37,211,102,0.25)', borderRadius: 100, padding: '4px 14px',
        fontSize: 11, fontWeight: 700, color: '#25D366', letterSpacing: '0.06em', textTransform: 'uppercase',
        marginBottom: 24,
      }}>
        🔒 Fonctionnalité Pro
      </div>

      <h2 style={{ fontFamily: 'Syne,sans-serif', fontWeight: 800, fontSize: 26, color: '#e8f5ec', marginBottom: 10, lineHeight: 1.2 }}>
        WhatsApp Business API
      </h2>
      <p style={{ fontSize: 14, color: '#7aab88', lineHeight: 1.7, marginBottom: 8 }}>
        Disponible exclusivement avec le plan <strong style={{ color: '#25D366' }}>Pro WhatsApp</strong>.
      </p>
      <p style={{ fontSize: 13, color: '#5a8a6a', marginBottom: 32 }}>
        Votre plan actuel : <strong style={{ color: '#fbbf24' }}>{currentLabel}</strong>
      </p>

      {/* Features grid */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: 10, marginBottom: 32, textAlign: 'left',
      }}>
        {FEATURES.map(({ icon, text }) => (
          <div key={text} style={{
            display: 'flex', alignItems: 'flex-start', gap: 10,
            background: 'rgba(37,211,102,0.05)', border: '1px solid rgba(37,211,102,0.12)',
            borderRadius: 12, padding: '10px 14px',
          }}>
            <span style={{ fontSize: 18, flexShrink: 0 }}>{icon}</span>
            <span style={{ fontSize: 13, color: '#c8e8d4', lineHeight: 1.4 }}>{text}</span>
          </div>
        ))}
      </div>

      {/* Price block */}
      <div style={{
        background: 'rgba(37,211,102,0.08)', border: '1px solid rgba(37,211,102,0.25)',
        borderRadius: 16, padding: '20px 24px', marginBottom: 24,
        display: 'flex', justifyContent: 'center', alignItems: 'baseline', gap: 6,
      }}>
        <span style={{ fontFamily: 'Syne,sans-serif', fontWeight: 900, fontSize: 36, color: '#25D366' }}>49,99</span>
        <span style={{ fontSize: 16, color: '#7aab88', fontWeight: 600 }}>DT/mois</span>
        <span style={{ fontSize: 13, color: '#5a8a6a', marginLeft: 8 }}>ou 499 DT/an</span>
      </div>

      {/* CTA */}
      <button
        onClick={handleUpgrade}
        style={{
          background: 'linear-gradient(135deg,#25D366,#128C7E)',
          color: '#fff', border: 'none', borderRadius: 14,
          padding: '14px 32px', fontSize: 15, fontWeight: 700, cursor: 'pointer',
          width: '100%', marginBottom: 20,
          boxShadow: '0 4px 20px rgba(37,211,102,0.3)',
          transition: 'opacity 0.2s',
        }}
        onMouseOver={e => e.currentTarget.style.opacity = '0.9'}
        onMouseOut={e => e.currentTarget.style.opacity = '1'}
      >
        Passer au Pro WhatsApp →
      </button>

      {/* Meta disclaimer — obligatoire */}
      <div style={{
        background: 'rgba(251,191,36,0.07)', border: '1px solid rgba(251,191,36,0.2)',
        borderRadius: 10, padding: '10px 16px',
        fontSize: 12, color: '#fbbf24', lineHeight: 1.5, textAlign: 'left',
      }}>
        <strong>⚠️ Important :</strong> Les frais Meta WhatsApp (messages sortants, templates, etc.) ne sont pas inclus dans l'abonnement Pro WhatsApp. Ils sont facturés directement par Meta selon votre usage.{' '}
        <a href="https://business.whatsapp.com/products/platform-pricing" target="_blank" rel="noopener noreferrer" style={{ color: '#fbbf24', textDecoration: 'underline' }}>
          Voir la grille Meta →
        </a>
      </div>
    </div>
  );
}

/* ─── CompletenessBar ────────────────────────────────────────────────────────── */
function CompletenessBar({ completeness, storeData }) {
  if (!completeness) return null;
  const { score, is_online, required_missing, recommended_missing, public_url, slug } = completeness;
  const publicUrl = public_url || `${window.location.origin}/store/${slug}`;

  return (
    <div style={{
      background: is_online ? 'rgba(37,211,102,0.06)' : 'rgba(251,191,36,0.06)',
      border: `1px solid ${is_online ? 'rgba(37,211,102,0.25)' : 'rgba(251,191,36,0.25)'}`,
      borderRadius:16, padding:'16px 20px', marginBottom:20,
    }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:10, flexWrap:'wrap', gap:10 }}>
        <div style={{ display:'flex', alignItems:'center', gap:10 }}>
          <span style={{ fontSize:20 }}>{is_online ? '✅' : '⚠️'}</span>
          <div>
            <div style={{ fontWeight:700, fontSize:14, color:'#e8f5ec' }}>
              {is_online ? 'Boutique en ligne 🟢' : 'Configuration incomplète'}
            </div>
            <div style={{ fontSize:12, color:'#7aab88' }}>
              {is_online ? `Visible sur ${publicUrl}` : `${required_missing?.length || 0} élément(s) requis manquants`}
            </div>
          </div>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          <div style={{ textAlign:'right' }}>
            <div style={{ fontFamily:'Syne,sans-serif', fontWeight:800, fontSize:22, color: score===100?'#25D366':score>=60?'#fbbf24':'#f87171' }}>{score}%</div>
            <div style={{ fontSize:11, color:'#7aab88' }}>Complétude</div>
          </div>
          {is_online && (
            <a href={`/store/${slug}`} target="_blank" rel="noopener noreferrer"
              style={{ background:'#25D366', color:'#000', padding:'8px 16px', borderRadius:10, fontSize:13, fontWeight:700, textDecoration:'none' }}>
              👁️ Voir
            </a>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div style={{ height:6, background:'rgba(37,211,102,0.1)', borderRadius:3, overflow:'hidden', marginBottom:10 }}>
        <div style={{ height:'100%', width:`${score}%`, background: score===100?'#25D366':score>=60?'#fbbf24':'#f87171', borderRadius:3, transition:'width 0.5s ease' }}/>
      </div>

      {/* Manquants */}
      {required_missing?.length > 0 && (
        <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
          {required_missing.map(item => (
            <span key={item.key} style={{ background:'rgba(248,113,113,0.1)', border:'1px solid rgba(248,113,113,0.25)', color:'#f87171', fontSize:11, fontWeight:600, padding:'3px 10px', borderRadius:100 }}>
              ❌ {item.label}
            </span>
          ))}
          {recommended_missing?.slice(0,3).map(item => (
            <span key={item.key} style={{ background:'rgba(251,191,36,0.08)', border:'1px solid rgba(251,191,36,0.2)', color:'#fbbf24', fontSize:11, padding:'3px 10px', borderRadius:100 }}>
              💡 {item.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}


export default function Settings({ initialTab = 'store' }) {
  const { api, refreshStore } = useStore();
  // P1.1 FIX: initialTab comes from the route (e.g. /settings/whatsapp → initialTab="whatsapp")
  // This enables deep-linking — refresh on /settings/ai keeps the AI tab open
  const [tab, setTab] = useState(initialTab);
  const [storeData, setStoreData] = useState(null);
  const [completeness, setCompleteness] = useState(null);
  const [showCongrats, setShowCongrats] = useState(false);
  const [phones, setPhones] = useState([]);
  const [paymentCfg, setPaymentCfg] = useState({});
  const [users, setUsers] = useState([]);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [socialStatus, setSocialStatus] = useState({ instagram: {}, facebook: {}, tiktok: {} });
  const [whatsappGate, setWhatsappGate] = useState(null);

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  };

  useEffect(() => { loadAll(); }, [tab]);

  // ── P0 FIX (CTO audit) ─────────────────────────────────────────────────────
  // Avant : Promise.all → un seul 404/500 plantait TOUT le bloc et storeData
  //          restait null → la page Settings refusait de se rendre.
  // Après : Promise.allSettled + fallbacks par appel → chaque endpoint est isolé,
  //          les onglets indépendants ne se contaminent plus mutuellement.
  //          Zéro-régression : même contrat de state qu'avant, juste résilient.
  // ───────────────────────────────────────────────────────────────────────────
  const loadAll = async () => {
    const settle = async (req, fallback = null) => {
      try { const res = await req; return res?.data ?? fallback; }
      catch (e) {
        // 404 → endpoint absent (rétro-compat) ; on log mais on ne casse pas la page
        const status = e?.response?.status;
        if (status && status !== 404) console.warn('[Settings] load partial failure:', status, e?.config?.url);
        return fallback;
      }
    };

    const [
      storeData_, phonesData, payData, usersData, socialData, completenessData, gateData,
    ] = await Promise.all([
      settle(api.get('/settings/store'), null),
      // WhatsApp endpoints are plan-gated; load them only when the user opens that tab.
      tab === 'whatsapp' ? settle(api.get('/whatsapp/registered-phones'), []) : Promise.resolve([]),
      settle(api.get('/settings/payments'), { providers: {} }),
      settle(api.get('/settings/users'), []),
      settle(api.get('/social/status'), { instagram: {}, facebook: {}, tiktok: {} }),
      settle(api.get('/settings/store/completeness'), null),
      tab === 'whatsapp' ? settle(api.get('/billing/whatsapp-gate'), null) : Promise.resolve(null),
    ]);

    // storeData est le seul appel critique — s'il échoue, on affiche un message
    // mais on n'empêche plus les autres onglets de s'afficher.
    if (storeData_) setStoreData(storeData_);
    else showToast('Impossible de charger les paramètres boutique', 'error');

    if (completenessData) setCompleteness(completenessData);
    setPhones(Array.isArray(phonesData) ? phonesData : []);
    setPaymentCfg(payData?.providers || {});
    setUsers(Array.isArray(usersData) ? usersData : []);
    setSocialStatus(socialData || { instagram: {}, facebook: {}, tiktok: {} });
    if (gateData) setWhatsappGate(gateData);
  };

  const saveStore = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch('/settings/store', storeData);
      // Réinjecter la réponse serveur dans le contexte global : la devise choisie
      // devient immédiatement visible dans le dashboard et les autres pages.
      const refreshedStore = await refreshStore();
      if (refreshedStore) setStoreData(refreshedStore);
      // Recharger complétude après sauvegarde
      try {
        const comp = await api.get('/settings/store/completeness');
        if (comp?.data) {
          const prevOnline = completeness?.is_online;
          setCompleteness(comp.data);
          if (!prevOnline && comp.data.is_online) setShowCongrats(true);
          else if (comp.data.is_online) setShowCongrats(true);
        }
      } catch(e) { console.error('completeness:', e); }
      showToast('Paramètres sauvegardés ✅');
    } catch { showToast('Erreur lors de la sauvegarde', 'error'); }
    finally { setSaving(false); }
  };

  return (
    <div className="space-y-4 lg:space-y-6">
      <h1 className="text-xl lg:text-2xl font-bold text-gray-900">Paramètres</h1>

      {/* Toast */}
      {toast && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-white text-sm font-medium ${toast.type === 'error' ? 'bg-red-500' : 'bg-green-500'}`}>
          {toast.msg}
        </div>
      )}

      {/* Tab bar - Responsive */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 overflow-x-auto">
        {TABS.map(t => {
          const isWaLocked = t.id === 'whatsapp' && whatsappGate !== null && !whatsappGate.enabled;
          return (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`px-3 lg:px-4 py-2 rounded-md text-xs lg:text-sm font-medium transition-all whitespace-nowrap ${tab === t.id ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
              {t.label}{isWaLocked ? ' 🔒' : ''}
            </button>
          );
        })}
      </div>

      {/* ── Store tab ── */}
      {showCongrats && storeData && (
        <CongratsModal store={storeData} onClose={() => setShowCongrats(false)} />
      )}

      {tab === 'store' && storeData && (
        <>
        <CompletenessBar completeness={completeness} storeData={storeData} />
        <form onSubmit={saveStore} className="bg-white rounded-lg lg:rounded-2xl p-4 lg:p-6 shadow-sm border border-gray-100 space-y-4 max-w-2xl">
          <h2 className="font-semibold text-gray-900 text-sm lg:text-base">Informations boutique</h2>
          {[
            ['name', 'Nom de la boutique', 'text'],
            ['description', 'Description de la boutique', 'textarea'],
            ['category', 'Catégorie (ex: Mode, Auto, Beauté...)', 'text'],
            ['address', 'Adresse physique', 'text'],
            ['phone_display', 'Téléphone affiché', 'text'],
            ['website_url', 'Site web (optionnel)', 'url'],
            ['support_email', 'Email de contact', 'email'],
            ['logo_url', 'URL du logo', 'text'],
            ['stock_api_url', 'URL API stock externe', 'text'],
          ].map(([key, label, type]) => (
            <div key={key}>
              <label className="block text-xs lg:text-sm text-gray-600 mb-1">{label}</label>
              <input type={type} value={storeData[key] || ''} onChange={e => setStoreData({ ...storeData, [key]: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-gray-300 outline-none" />
            </div>
          ))}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs lg:text-sm text-gray-600 mb-1">Langue</label>
              <select value={storeData.language || 'fr'} onChange={e => setStoreData({ ...storeData, language: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none">
                <option value="fr">Français</option>
                <option value="ar">العربية</option>
                <option value="en">English</option>
                <option value="de">Deutsch</option>
                <option value="es">Español</option>
                <option value="it">Italiano</option>
              </select>
            </div>
            <div>
              <label className="block text-xs lg:text-sm text-gray-600 mb-1">Timeout conversation (min)</label>
              <input type="number" min="5" max="120" value={storeData.conversation_timeout_min || 30}
                onChange={e => setStoreData({ ...storeData, conversation_timeout_min: parseInt(e.target.value) })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none" />
            </div>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs lg:text-sm text-gray-600 mb-1">Pays de la boutique</label>
              <select value={storeData.country || 'TN'} onChange={e => {
                const country = e.target.value;
                const option = COUNTRY_OPTIONS.find(([code]) => code === country);
                setStoreData({ ...storeData, country, default_tax_country: country, currency: option?.[2] || storeData.currency || 'TND' });
              }} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none">
                {COUNTRY_OPTIONS.map(([code, label]) => <option key={code} value={code}>{label} ({code})</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs lg:text-sm text-gray-600 mb-1">Devise de règlement</label>
              <select value={storeData.currency || 'TND'} onChange={e => setStoreData({ ...storeData, currency: e.target.value })} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none">
                {CURRENCY_OPTIONS.map(code => <option key={code} value={code}>{code}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs lg:text-sm text-gray-600 mb-1">Fuseau horaire</label>
              <input value={storeData.timezone || 'Africa/Tunis'} onChange={e => setStoreData({ ...storeData, timezone: e.target.value })} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none" placeholder="Europe/Paris" />
            </div>
          </div>

          <div className="border-t border-gray-100 pt-4 mt-4">
            <h3 className="text-xs font-bold text-gray-400 uppercase mb-3">Vitrine Publique (Extra)</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Coordonnées GPS (Lat)</label>
                <input type="number" step="any" value={storeData?.latitude || ''} onChange={e => setStoreData({...storeData, latitude: parseFloat(e.target.value)})} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" placeholder="ex: 36.80" />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-600 mb-1">Coordonnées GPS (Lon)</label>
                <input type="number" step="any" value={storeData?.longitude || ''} onChange={e => setStoreData({...storeData, longitude: parseFloat(e.target.value)})} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" placeholder="ex: 10.18" />
              </div>
            </div>
            <div className="mt-4">
              <label className="block text-xs font-semibold text-gray-600 mb-1">Réseaux Sociaux (Liens publics)</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {['instagram', 'tiktok', 'youtube', 'messenger'].map(net => (
                  <input key={net} type="text" placeholder={`Lien ${net}`} value={storeData?.social_links?.[net] || ''} 
                    onChange={e => setStoreData({...storeData, social_links: {...(storeData.social_links||{}), [net]: e.target.value}})} 
                    className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
                ))}
              </div>
            </div>
          </div>
          <button type="submit" disabled={saving}
            className="bg-gray-900 text-white px-6 py-2 rounded-lg hover:bg-gray-800 disabled:opacity-60 text-sm font-medium">
            {saving ? 'Sauvegarde...' : 'Sauvegarder'}
          </button>
        </form>
        </>
      )}

      {/* ── WhatsApp tab ── */}
      {tab === 'whatsapp' && (
        <div className="space-y-4 max-w-4xl">
          {/* Gate check */}
          {whatsappGate !== null && !whatsappGate.enabled ? (
            <WhatsAppUpgradeWall gate={whatsappGate} />
          ) : (
            <>
              {/* Disclaimer Meta — toujours visible même si activé */}
              <div style={{
                background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.25)',
                borderRadius: 12, padding: '10px 16px', fontSize: 13, color: '#92400e',
                display: 'flex', alignItems: 'flex-start', gap: 8,
              }}>
                <span style={{ flexShrink: 0 }}>⚠️</span>
                <span>
                  <strong>Frais Meta non inclus.</strong> Les frais WhatsApp Business (messages sortants, templates, conversations) sont facturés séparément par Meta selon votre usage.{' '}
                  <a href="https://business.whatsapp.com/products/platform-pricing" target="_blank" rel="noopener noreferrer" style={{ color: '#b45309', textDecoration: 'underline' }}>
                    Voir la grille de prix Meta →
                  </a>
                </span>
              </div>

              {/* Numéros enregistrés */}
              <div className="bg-white rounded-lg lg:rounded-2xl p-4 lg:p-6 shadow-sm border border-gray-100">
                <h2 className="font-semibold text-gray-900 mb-4 text-sm lg:text-base">Numéros enregistrés</h2>
                {phones.length === 0 ? (
                  <p className="text-gray-400 text-sm">Aucun numéro enregistré</p>
                ) : (
                  <div className="space-y-2">
                    {phones.map((p, i) => (
                      <div key={i} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 lg:px-4 py-2 lg:py-3">
                        <div>
                          <p className="font-medium text-gray-900 text-sm">{p.display_phone || '—'}</p>
                          <p className="text-xs text-gray-400">ID: {p.phone_number_id}</p>
                        </div>
                        <span className="text-green-600 text-xs font-medium bg-green-100 px-2 py-1 rounded-full">✅ Actif</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Formulaire enregistrement */}
              <RegisterPhoneForm api={api} onSuccess={() => { loadAll(); showToast('Numéro enregistré ✅'); }} onError={(m) => showToast(m, 'error')} />

              {/* ── Mode Admin Conversationnel ── */}
              <OwnerAdminSection api={api} showToast={showToast} />

              {/* Simulateur WhatsApp */}
              <WhatsAppSimulator storeName={storeData?.name || 'Ma Boutique'} />
            </>
          )}
        </div>
      )}

      {/* ── Payments tab ── */}
      {tab === 'payments' && (
        <div className="space-y-4 max-w-2xl">
          {PROVIDERS.map(provider => (
            <PaymentProviderCard
              key={provider}
              provider={provider}
              current={paymentCfg[provider]}
              api={api}
              onSave={() => { loadAll(); showToast(`${provider} configuré ✅`); }}
              onError={(m) => showToast(m, 'error')}
            />
          ))}
        </div>
      )}

      {/* ── Users tab ── */}
      {tab === 'users' && (
        <div className="space-y-4 max-w-2xl">
          <div className="bg-white rounded-lg lg:rounded-2xl p-4 lg:p-6 shadow-sm border border-gray-100">
            <h2 className="font-semibold text-gray-900 mb-4 text-sm lg:text-base">Membres de l'équipe</h2>
            <div className="divide-y divide-gray-50">
              {users.map(u => (
                <div key={u.id} className="flex items-center justify-between py-3">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{u.email}</p>
                    <span className={`text-xs px-2 py-0.5 rounded-full ${u.role === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-gray-100 text-gray-600'}`}>
                      {u.role}
                    </span>
                  </div>
                  <span className="text-xs text-gray-400">{new Date(u.created_at).toLocaleDateString('fr-TN')}</span>
                </div>
              ))}
            </div>
          </div>
          <InviteUserForm api={api} onSuccess={() => { loadAll(); showToast('Utilisateur invité ✅'); }} onError={(m) => showToast(m, 'error')} />
        </div>
      )}

      {/* ── Agent IA tab ── */}
      {tab === 'agent' && storeData && (
        <div className="space-y-6">
          <form onSubmit={saveStore} className="bg-white rounded-lg lg:rounded-2xl p-4 lg:p-6 shadow-sm border border-gray-100 space-y-4 max-w-2xl">
            <h2 className="font-semibold text-gray-900 text-sm lg:text-base">Configuration Agent IA</h2>
            {[
              ['ai_agent_prompt', 'Prompt personnalisé (instructions supplémentaires)', 4],
              ['order_confirmation_msg', 'Message de confirmation commande', 2],
              ['post_payment_msg', 'Message post-paiement automatique', 2],
            ].map(([key, label, rows]) => (
              <div key={key}>
                <label className="block text-xs lg:text-sm text-gray-600 mb-1">{label}</label>
                <textarea rows={rows} value={storeData[key] || ''}
                  onChange={e => setStoreData({ ...storeData, [key]: e.target.value })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-gray-300 outline-none resize-none"
                  placeholder="Laisser vide pour utiliser les messages par défaut" />
              </div>
            ))}
            <button type="submit" disabled={saving}
              className="bg-gray-900 text-white px-6 py-2 rounded-lg hover:bg-gray-800 disabled:opacity-60 text-sm font-medium">
              {saving ? 'Sauvegarde...' : 'Sauvegarder'}
            </button>
          </form>

          {/* Configuration avancée des sources de stock et OEM */}
          <div className="max-w-4xl">
            <StockSources />
          </div>
        </div>
      )}

      {/* ── Réseaux sociaux tab ── */}
      {tab === 'social' && (
        <div className="space-y-4 max-w-2xl">
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
            <p className="text-xs text-blue-800">
              <strong>🔐 Stockage sécurisé.</strong> Vos tokens réseaux sociaux sont chiffrés (AES-256) avant stockage.
              Ils ne sont jamais affichés ni transmis en clair. Chaque boutique utilise ses propres clés d'API.
            </p>
          </div>
          <SocialNetworkCard
            network="instagram"
            label="Instagram"
            icon="📸"
            color="pink"
            status={socialStatus.instagram}
            fields={[
              { key: 'access_token', label: 'Access Token (Graph API)', type: 'password', required: true },
              { key: 'account_id', label: 'Instagram Business Account ID', type: 'text', required: true },
              { key: 'username', label: 'Nom d\'utilisateur (affiché)', type: 'text', required: false },
            ]}
            helpUrl="https://developers.facebook.com/docs/instagram-api/getting-started"
            helpText="Générez un token depuis Meta for Developers → votre App → Instagram Graph API"
            api={api}
            onSuccess={() => { loadAll(); showToast('Instagram connecté ✅'); }}
            onDisconnect={() => { loadAll(); showToast('Instagram déconnecté'); }}
            onError={(m) => showToast(m, 'error')}
          />
          <SocialNetworkCard
            network="facebook"
            label="Facebook"
            icon="📘"
            color="blue"
            status={socialStatus.facebook}
            fields={[
              { key: 'access_token', label: 'Page Access Token', type: 'password', required: true },
              { key: 'page_id', label: 'Facebook Page ID', type: 'text', required: true },
              { key: 'page_name', label: 'Nom de la page (affiché)', type: 'text', required: false },
            ]}
            helpUrl="https://developers.facebook.com/docs/pages/access-tokens"
            helpText="Générez un Page Access Token depuis Meta Business Suite → Paramètres → Accès API"
            api={api}
            onSuccess={() => { loadAll(); showToast('Facebook connecté ✅'); }}
            onDisconnect={() => { loadAll(); showToast('Facebook déconnecté'); }}
            onError={(m) => showToast(m, 'error')}
          />
          <SocialNetworkCard
            network="tiktok"
            label="TikTok"
            icon="🎵"
            color="gray"
            status={socialStatus.tiktok}
            fields={[
              { key: 'access_token', label: 'Access Token (TikTok for Business)', type: 'password', required: true },
              { key: 'open_id', label: 'Open ID (identifiant compte)', type: 'text', required: true },
              { key: 'username', label: 'Nom d\'utilisateur TikTok', type: 'text', required: false },
            ]}
            helpUrl="https://developers.tiktok.com/doc/tiktok-api-v2-get-started"
            helpText="Créez une App sur TikTok for Developers et utilisez le Login Kit pour obtenir votre access token"
            api={api}
            onSuccess={() => { loadAll(); showToast('TikTok connecté ✅'); }}
            onDisconnect={() => { loadAll(); showToast('TikTok déconnecté'); }}
            onError={(m) => showToast(m, 'error')}
          />
        </div>
      )}
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────────
function RegisterPhoneForm({ api, onSuccess, onError }) {
  const [form, setForm] = useState({ phone_number_id: '', display_phone: '' });
  const [loading, setLoading] = useState(false);
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try { await api.post('/whatsapp/register-phone', form); onSuccess(); setForm({ phone_number_id: '', display_phone: '' }); }
    catch (err) { onError && onError(err?.response?.data?.detail || 'Erreur lors de l\'enregistrement'); }
    finally { setLoading(false); }
  };
  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-lg lg:rounded-2xl p-4 lg:p-6 shadow-sm border border-gray-100 space-y-3">
      <h3 className="font-medium text-gray-900 text-sm lg:text-base">Enregistrer un numéro WhatsApp</h3>
      <div>
        <label className="block text-xs lg:text-sm text-gray-600 mb-1">Phone Number ID (Meta)</label>
        <input required value={form.phone_number_id} onChange={e => setForm({ ...form, phone_number_id: e.target.value })}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none" placeholder="123456789012345" />
      </div>
      <div>
        <label className="block text-xs lg:text-sm text-gray-600 mb-1">Numéro d'affichage</label>
        <input value={form.display_phone} onChange={e => setForm({ ...form, display_phone: e.target.value })}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none" placeholder="+21698765432" />
      </div>
      <button type="submit" disabled={loading} className="bg-green-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-green-700 disabled:opacity-60">
        {loading ? '...' : '➕ Enregistrer'}
      </button>
    </form>
  );
}

function PaymentProviderCard({ provider, current, api, onSave, onError }) {
  const [form, setForm] = useState({ api_key: '', secret_key: '', sandbox: false });
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const icons = { stripe: '💳', flouci: '🔵', clix: '🟢', tnpay: '🟠', cmi: '🇲🇦', aliapay: '🇩🇿', nexus: '🌍', cash: '💵' };
  const handleSave = async (e) => {
    e.preventDefault();
    setLoading(true);
    try { await api.post('/settings/payments', { provider, ...form, enabled: true }); onSave(); setOpen(false); }
    catch (err) { onError && onError(err?.response?.data?.detail || 'Erreur configuration'); }
    finally { setLoading(false); }
  };
  return (
    <div className="bg-white rounded-lg lg:rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
      <div className="flex items-center justify-between px-4 lg:px-6 py-3 lg:py-4 cursor-pointer" onClick={() => setOpen(!open)}>
        <div className="flex items-center gap-3">
          <span className="text-2xl">{icons[provider]}</span>
          <div>
            <p className="font-semibold text-gray-900 capitalize text-sm">{provider}</p>
            <p className="text-xs text-gray-400">{current ? '✅ Configuré' : '⚠️ Non configuré'}</p>
          </div>
        </div>
        <span className="text-gray-400 text-sm">{open ? '▲' : '▼'}</span>
      </div>
      {open && (
        <form onSubmit={handleSave} className="px-4 lg:px-6 pb-4 space-y-3 border-t border-gray-50">
          {provider !== 'cash' && (
            <>
              <div>
                <label className="block text-xs lg:text-sm text-gray-600 mb-1">API Key</label>
                <input type="password" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none" placeholder="Laisser vide pour conserver" />
              </div>
              {provider === 'flouci' && (
                <div>
                  <label className="block text-xs lg:text-sm text-gray-600 mb-1">Secret Key</label>
                  <input type="password" value={form.secret_key} onChange={e => setForm({ ...form, secret_key: e.target.value })}
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none" />
                </div>
              )}
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={form.sandbox} onChange={e => setForm({ ...form, sandbox: e.target.checked })} />
                <span className="text-xs lg:text-sm text-gray-600">Mode sandbox (test)</span>
              </label>
            </>
          )}
          <button type="submit" disabled={loading}
            className="bg-gray-900 text-white px-5 py-2 rounded-lg text-sm hover:bg-gray-800 disabled:opacity-60">
            {loading ? '...' : 'Enregistrer'}
          </button>
        </form>
      )}
    </div>
  );
}

function InviteUserForm({ api, onSuccess, onError }) {
  const [form, setForm] = useState({ email: '', password: '', role: 'viewer' });
  const [loading, setLoading] = useState(false);
  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try { await api.post('/settings/users', form); onSuccess(); setForm({ email: '', password: '', role: 'viewer' }); }
    catch (err) { onError && onError(err?.response?.data?.detail || 'Erreur'); }
    finally { setLoading(false); }
  };
  return (
    <form onSubmit={handleSubmit} className="bg-white rounded-lg lg:rounded-2xl p-4 lg:p-6 shadow-sm border border-gray-100 space-y-3">
      <h3 className="font-medium text-gray-900 text-sm lg:text-base">Inviter un membre</h3>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs lg:text-sm text-gray-600 mb-1">Email</label>
          <input type="email" required value={form.email} onChange={e => setForm({ ...form, email: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none" />
        </div>
        <div>
          <label className="block text-xs lg:text-sm text-gray-600 mb-1">Mot de passe</label>
          <input type="password" required value={form.password} onChange={e => setForm({ ...form, password: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none" />
        </div>
      </div>
      <div>
        <label className="block text-xs lg:text-sm text-gray-600 mb-1">Rôle</label>
        <select value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none">
          <option value="viewer">Viewer (lecture seule)</option>
          <option value="admin">Admin (accès complet)</option>
        </select>
      </div>
      <button type="submit" disabled={loading} className="bg-gray-900 text-white px-5 py-2 rounded-lg text-sm hover:bg-gray-800 disabled:opacity-60">
        {loading ? '...' : '➕ Inviter'}
      </button>
    </form>
  );
}

// ── WhatsApp Simulator Component ──────────────────────────────────────────────
function WhatsAppSimulator({ storeName }) {
  const [messages, setMessages] = useState([
    { type: 'user', text: 'Bonjour 👋' },
    { type: 'bot', text: `Bienvenue à ${storeName}! 🎉\n\nComment puis-je vous aider aujourd'hui?` },
  ]);
  const [inputValue, setInputValue] = useState('');

  const handleSendMessage = () => {
    if (!inputValue.trim()) return;
    setMessages([
      ...messages,
      { type: 'user', text: inputValue },
      { type: 'bot', text: 'Merci pour votre message! Notre équipe vous répondra bientôt. 📧' },
    ]);
    setInputValue('');
  };

  return (
    <div className="bg-white rounded-lg lg:rounded-2xl p-4 lg:p-6 shadow-sm border border-gray-100">
      <h3 className="font-semibold text-gray-900 mb-4 text-sm lg:text-base">📱 Simulateur WhatsApp</h3>
      
      {/* Simulateur */}
      <div className="flex flex-col lg:flex-row gap-4">
        {/* Aperçu du téléphone */}
        <div className="flex-1 bg-gradient-to-b from-gray-900 to-gray-800 rounded-3xl p-3 shadow-lg max-w-sm mx-auto lg:mx-0">
          <div className="bg-white rounded-2xl overflow-hidden shadow-xl">
            {/* Header WhatsApp */}
            <div className="bg-green-600 text-white px-4 py-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-lg">💬</span>
                <div>
                  <p className="font-bold text-sm">{storeName}</p>
                  <p className="text-xs text-green-100">En ligne</p>
                </div>
              </div>
              <div className="flex gap-2 text-lg">📞 ⓘ</div>
            </div>

            {/* Messages */}
            <div className="h-64 bg-gray-50 overflow-y-auto p-3 space-y-3">
              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-xs px-3 py-2 rounded-lg text-sm ${
                    msg.type === 'user'
                      ? 'bg-green-100 text-gray-900'
                      : 'bg-white text-gray-900 border border-gray-200'
                  }`}>
                    {msg.text}
                  </div>
                </div>
              ))}
            </div>

            {/* Input */}
            <div className="border-t border-gray-200 px-3 py-2 flex gap-2 bg-white">
              <input
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
                placeholder="Tapez un message..."
                className="flex-1 text-sm outline-none"
              />
              <button
                onClick={handleSendMessage}
                className="text-green-600 font-bold text-lg hover:text-green-700"
              >
                ➤
              </button>
            </div>
          </div>
        </div>

        {/* Infos et conseils */}
        <div className="flex-1 space-y-4">
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <p className="text-xs lg:text-sm font-semibold text-blue-900 mb-2">💡 Conseil</p>
            <p className="text-xs lg:text-sm text-blue-800">
              Ce simulateur montre comment vos clients verront votre boutique sur WhatsApp. Testez différents messages pour améliorer l'expérience utilisateur.
            </p>
          </div>

          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <p className="text-xs lg:text-sm font-semibold text-green-900 mb-2">✅ Fonctionnalités</p>
            <ul className="text-xs lg:text-sm text-green-800 space-y-1">
              <li>• Réponses automatiques 24/7</li>
              <li>• Catalogue de produits intégré</li>
              <li>• Paiement sécurisé</li>
              <li>• Suivi de commande en temps réel</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── OwnerAdminSection ────────────────────────────────────────────────────────
function OwnerAdminSection({ api, showToast }) {
  const [ownerPhone, setOwnerPhone] = React.useState('');
  const [saved, setSaved] = React.useState('');
  const [loading, setLoading] = React.useState(false);

  // Charger le owner_phone actuel depuis le store
  React.useEffect(() => {
    api.get('/stores/me').then(d => {
      if (d?.owner_phone) { setOwnerPhone(d.owner_phone); setSaved(d.owner_phone); }
    }).catch((e) => console.error('settings load:', e));
  }, []);

  const save = async () => {
    setLoading(true);
    try {
      if (ownerPhone.trim()) {
        await api.put('/whatsapp/owner-phone', { owner_phone: ownerPhone.trim() });
        setSaved(ownerPhone.trim());
        showToast('Mode admin WhatsApp activé ✅');
      } else {
        await api.delete('/whatsapp/owner-phone');
        setSaved('');
        showToast('Mode admin désactivé');
      }
    } catch (e) {
      showToast('Erreur : ' + (e?.message || 'inconnue'), 'error');
    } finally { setLoading(false); }
  };

  const COMMANDS = [
    { cmd: 'stock', desc: 'Voir tout le stock' },
    { cmd: 'stock t-shirt', desc: 'Stock d\'un produit' },
    { cmd: 'commandes', desc: 'Résumé du jour' },
    { cmd: 'commandes semaine', desc: '7 derniers jours' },
    { cmd: 'rapport', desc: 'Rapport complet' },
    { cmd: 'clients', desc: 'Statistiques clients' },
    { cmd: 'broadcast <message>', desc: 'Envoyer à tous les clients' },
    { cmd: 'alerte stock 5', desc: 'Alerte si stock < N' },
  ];

  return (
    <div className="bg-white rounded-lg lg:rounded-2xl p-4 lg:p-6 shadow-sm border border-gray-100">
      {/* Header */}
      <div className="flex items-start gap-3 mb-5">
        <div className="w-10 h-10 rounded-xl bg-green-100 flex items-center justify-center text-xl flex-shrink-0">🤖</div>
        <div>
          <h2 className="font-semibold text-gray-900 text-sm lg:text-base">Mode Admin Conversationnel</h2>
          <p className="text-xs text-gray-500 mt-0.5">Gérez votre boutique depuis WhatsApp, en écrivant des commandes naturelles.</p>
        </div>
        {saved && (
          <span className="ml-auto text-xs font-semibold bg-green-100 text-green-700 px-2 py-1 rounded-full flex-shrink-0">✅ Actif</span>
        )}
      </div>

      {/* Phone input */}
      <div className="mb-4">
        <label className="block text-xs font-semibold text-gray-600 mb-1.5">
          Votre numéro WhatsApp personnel (marchand)
        </label>
        <div className="flex gap-2">
          <input
            type="tel"
            value={ownerPhone}
            onChange={e => setOwnerPhone(e.target.value)}
            placeholder="+21612345678"
            className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-green-400 focus:ring-1 focus:ring-green-200"
          />
          <button
            onClick={save}
            disabled={loading}
            className="bg-green-500 hover:bg-green-600 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
          >
            {loading ? '...' : saved ? 'Modifier' : 'Activer'}
          </button>
          {saved && (
            <button
              onClick={() => { setOwnerPhone(''); save(); }}
              className="border border-red-200 text-red-500 text-sm px-3 py-2 rounded-lg hover:bg-red-50 transition-colors"
            >
              Désactiver
            </button>
          )}
        </div>
        <p className="text-xs text-gray-400 mt-1.5">
          ⚠️ Les messages de ce numéro ne seront <strong>jamais</strong> traités par l'agent client.
        </p>
      </div>

      {/* Commands grid */}
      <div className="border-t border-gray-100 pt-4">
        <p className="text-xs font-semibold text-gray-500 mb-3 uppercase tracking-wide">Commandes disponibles</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {COMMANDS.map(({ cmd, desc }) => (
            <div key={cmd} className="flex items-start gap-2 bg-gray-50 rounded-lg px-3 py-2">
              <code className="text-xs bg-white border border-gray-200 text-green-700 font-mono px-1.5 py-0.5 rounded flex-shrink-0">{cmd}</code>
              <span className="text-xs text-gray-500">{desc}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Example conversation */}
      <div className="border-t border-gray-100 pt-4 mt-4">
        <p className="text-xs font-semibold text-gray-500 mb-3 uppercase tracking-wide">Exemple de conversation</p>
        <div className="space-y-2 text-xs">
          {[
            { side: 'out', msg: 'stock t-shirt' },
            { side: 'in',  msg: '📦 Stock actuel :\n🟡 T-shirt Blanc : 3 unités | 29.900 DT\n🟢 T-shirt Noir : 12 unités | 29.900 DT\n\n⚠️ Stock bas : T-shirt Blanc' },
            { side: 'out', msg: 'commandes aujourd\'hui' },
            { side: 'in',  msg: '📋 Commandes — aujourd\'hui :\n📦 Total : 8 commandes\n✅ Confirmées : 6\n💰 CA : 287.400 DT' },
            { side: 'out', msg: 'broadcast Promo -20% ce weekend sur tout le catalogue !' },
            { side: 'in',  msg: '📢 Broadcast en attente\n👥 Destinataires : 142 clients\nRépondez OUI pour confirmer.' },
          ].map((m, i) => (
            <div key={i} className={`flex ${m.side === 'out' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-xs px-3 py-1.5 rounded-xl whitespace-pre-line ${
                m.side === 'out'
                  ? 'bg-green-500 text-white rounded-br-sm'
                  : 'bg-gray-100 text-gray-700 rounded-bl-sm'
              }`}>
                {m.msg}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── SocialNetworkCard ────────────────────────────────────────────────────────
function SocialNetworkCard({ network, label, icon, color, status, fields, helpUrl, helpText, api, onSuccess, onDisconnect, onError }) {
  const confirm = useConfirm();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({});
  const [loading, setLoading] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  const colorMap = {
    pink: { badge: 'bg-pink-100 text-pink-700', btn: 'bg-pink-600 hover:bg-pink-700', border: 'border-pink-200' },
    blue: { badge: 'bg-blue-100 text-blue-700', btn: 'bg-blue-600 hover:bg-blue-700', border: 'border-blue-200' },
    gray: { badge: 'bg-gray-100 text-gray-700', btn: 'bg-gray-900 hover:bg-gray-800', border: 'border-gray-200' },
  };
  const c = colorMap[color] || colorMap.gray;

  const handleConnect = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await api.post(`/social/${network}/connect`, form);
      setForm({});
      setOpen(false);
      onSuccess();
    } catch (err) {
      onError && onError(err?.response?.data?.detail || 'Erreur lors de la connexion');
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    if (!(await confirm(`Révoquer la connexion ${label} ? Le token sera supprimé définitivement.`))) return;
    setDisconnecting(true);
    try {
      await api.delete(`/social/${network}`);
      onDisconnect();
    } catch (err) {
      onError && onError('Erreur lors de la déconnexion');
    } finally {
      setDisconnecting(false);
    }
  };

  const metaLabel = network === 'instagram'
    ? status.username
    : network === 'facebook'
    ? status.page_name
    : status.username;

  return (
    <div className={`bg-white rounded-xl shadow-sm border ${status.connected ? c.border : 'border-gray-100'} overflow-hidden`}>
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="text-2xl">{icon}</span>
          <div>
            <p className="font-semibold text-gray-900 text-sm">{label}</p>
            {status.connected
              ? <p className="text-xs text-gray-500 mt-0.5">{metaLabel || 'Connecté'}</p>
              : <p className="text-xs text-gray-400 mt-0.5">Non connecté</p>
            }
          </div>
        </div>
        <div className="flex items-center gap-2">
          {status.connected && (
            <span className={`text-xs font-semibold px-2 py-1 rounded-full ${c.badge}`}>✅ Actif</span>
          )}
          {status.connected ? (
            <button onClick={handleDisconnect} disabled={disconnecting}
              className="text-xs border border-red-200 text-red-500 px-3 py-1.5 rounded-lg hover:bg-red-50 disabled:opacity-50 transition-colors">
              {disconnecting ? '...' : 'Révoquer'}
            </button>
          ) : (
            <button onClick={() => setOpen(!open)}
              className={`text-xs text-white px-3 py-1.5 rounded-lg transition-colors ${c.btn}`}>
              {open ? 'Annuler' : 'Connecter'}
            </button>
          )}
        </div>
      </div>

      {/* Formulaire de connexion */}
      {!status.connected && open && (
        <form onSubmit={handleConnect} className="px-5 pb-5 border-t border-gray-50 space-y-3 pt-4">
          {fields.map(({ key, label: fLabel, type, required }) => (
            <div key={key}>
              <label className="block text-xs text-gray-600 mb-1 font-medium">{fLabel}{required && <span className="text-red-400 ml-0.5">*</span>}</label>
              <input
                type={type}
                required={required}
                value={form[key] || ''}
                onChange={e => setForm({ ...form, [key]: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-gray-400 focus:ring-1 focus:ring-gray-200"
                placeholder={type === 'password' ? '••••••••••••••••' : ''}
                autoComplete="off"
              />
            </div>
          ))}

          {/* Aide */}
          <div className="bg-gray-50 rounded-lg p-3">
            <p className="text-xs text-gray-600">{helpText}</p>
            <a href={helpUrl} target="_blank" rel="noopener noreferrer"
              className="text-xs text-blue-600 hover:underline mt-1 inline-block">
              📖 Documentation officielle →
            </a>
          </div>

          <button type="submit" disabled={loading}
            className={`w-full text-white py-2 rounded-lg text-sm font-medium disabled:opacity-60 transition-colors ${c.btn}`}>
            {loading ? 'Connexion en cours...' : `🔗 Connecter ${label}`}
          </button>
        </form>
      )}

      {/* Détails si connecté */}
      {status.connected && (
        <div className="px-5 pb-4 pt-1 border-t border-gray-50">
          <div className="flex flex-wrap gap-3 text-xs text-gray-500">
            {network === 'instagram' && status.account_id && (
              <span>Account ID : <code className="bg-gray-100 px-1.5 py-0.5 rounded">{status.account_id}</code></span>
            )}
            {network === 'facebook' && status.page_id && (
              <span>Page ID : <code className="bg-gray-100 px-1.5 py-0.5 rounded">{status.page_id}</code></span>
            )}
            {network === 'tiktok' && status.open_id && (
              <span>Open ID : <code className="bg-gray-100 px-1.5 py-0.5 rounded">{status.open_id}</code></span>
            )}
            <span className="text-green-600">🔒 Token chiffré AES-256</span>
          </div>
        </div>
      )}
    </div>
  );
}
