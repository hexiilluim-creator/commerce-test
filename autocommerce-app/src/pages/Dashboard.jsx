import { useEffect, useState, useRef, useCallback } from 'react';
import { useStore } from '../context/StoreContext';
import { useTranslation } from 'react-i18next';
import { useToast } from '../context/ToastContext';
import i18next from 'i18next';
import { formatMoney, currencyLabel } from '../utils/currency';

// Configuration active de la boutique pour les sous-composants du dashboard.
// Elle est alimentée à chaque rendu par le tenant authentifié.
let activeStoreConfig = null;

// AUDIT FIX: Formatage monétaire configurable par tenant/localisation
// Au lieu d'être fixé à fr-TN/TND, utilise la langue i18n courante.
const fmt = (n, store = activeStoreConfig) => formatMoney(n, store || {}, i18next.language || 'fr');
const activeCurrency = () => currencyLabel(activeStoreConfig || {}, i18next.language || 'fr');
const fmtShort = (n) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : (n ?? 0).toString();
const pctColor = (p) => p >= 0 ? 'text-green-600' : 'text-red-500';
const pctSign  = (p) => p >= 0 ? `+${p}%` : `${p}%`;

function useSpendingCats() {
  const { t } = useTranslation();
  return [
    { id: 'supplier',  label: t('dashboard.cats.supplier'),  color: '#6366f1' },
    { id: 'fixed',     label: t('dashboard.cats.fixed'),     color: '#0ea5e9' },
    { id: 'marketing', label: t('dashboard.cats.marketing'), color: '#f59e0b' },
    { id: 'staff',     label: t('dashboard.cats.staff'),     color: '#10b981' },
    { id: 'logistics', label: t('dashboard.cats.logistics'), color: '#ef4444' },
    { id: 'other',     label: t('dashboard.cats.other'),     color: '#8b5cf6' },
  ];
}

const SPENDING_CATS = [
  { id: 'supplier',  label: '📦 Fournisseurs',  color: '#6366f1' },
  { id: 'fixed',     label: '🏢 Coûts fixes',    color: '#0ea5e9' },
  { id: 'marketing', label: '📢 Marketing',      color: '#f59e0b' },
  { id: 'staff',     label: '👥 Personnel',       color: '#10b981' },
  { id: 'logistics', label: '🚚 Logistique',     color: '#ef4444' },
  { id: 'other',     label: '📦 Autre',           color: '#8b5cf6' },
];
const catById = (id) => SPENDING_CATS.find(c => c.id === id) || SPENDING_CATS[5];

function usePeriodOpts() {
  const { t } = useTranslation();
  return [
    { v: '7d', l: t('dashboard.period7d') }, { v: '30d', l: t('dashboard.period30d') },
    { v: '90d', l: t('dashboard.period90d') }, { v: '12m', l: t('dashboard.period12m') },
  ];
}

const PERIOD_OPTS = [
  { v: '7d', l: '7 jours' }, { v: '30d', l: '30 jours' },
  { v: '90d', l: '90 jours' }, { v: '12m', l: '12 mois' },
];

function MiniBar({ data, valueKey, labelKey, color = '#6366f1', height = 80 }) {
  const { t } = useTranslation();
  if (!data?.length) return <div style={{ height }} className="flex items-center justify-center text-gray-300 text-sm">{t('dashboard.noData')}</div>;
  const max = Math.max(...data.map(d => d[valueKey])) || 1;
  return (
    <div className="flex items-end gap-0.5" style={{ height }}>
      {data.map((d, i) => (
        <div key={i} className="flex-1 flex flex-col items-center gap-0.5" title={`${d[labelKey]}: ${d[valueKey]}`}>
          <div className="w-full rounded-sm transition-all" style={{
            height: `${Math.max(2, (d[valueKey] / max) * (height - 20))}px`,
            background: color, opacity: 0.8,
          }} />
        </div>
      ))}
    </div>
  );
}

const CH_META = {
  whatsapp:  { icon: '💬', color: '#25D366', bg: '#f0fdf4', name: 'WhatsApp' },
  instagram: { icon: '📸', color: '#E1306C', bg: '#fff0f6', name: 'Instagram' },
  facebook:  { icon: '📘', color: '#1877F2', bg: '#eff6ff', name: 'Facebook' },
  tiktok:    { icon: '🎵', color: '#010101', bg: '#f8fafc', name: 'TikTok' },
};

// ══════════════════════════════════════════════════════════════════════════════
// A. MORNING BRIEF — Carte de résumé daily
// ══════════════════════════════════════════════════════════════════════════════
function MorningBrief({ overview, recentOrders, lowStock, api, onRefresh }) {
  const toast = useToast();
  const pendingOrders   = recentOrders.filter(o => o.status === 'pending');
  const urgentMessages  = overview?.messages?.urgent_30d ?? 0;
  const lowStockCount   = lowStock.length;
  const hasActions      = pendingOrders.length > 0 || urgentMessages > 0 || lowStockCount > 0;

  const now    = new Date();
  const hour   = now.getHours();
  const greet  = hour < 12 ? 'Bonjour' : hour < 18 ? 'Bon après-midi' : 'Bonsoir';

  const quickConfirm = async (orderId) => {
    try {
      await api.put(`/orders/${orderId}/status`, { status: 'confirmed' });
      toast.success(`Commande #${orderId} confirmée`);
      onRefresh();
    } catch { toast.error('Erreur lors de la confirmation'); }
  };

  return (
    <div className={`rounded-2xl border p-5 ${hasActions ? 'bg-amber-50 border-amber-200' : 'bg-gradient-to-r from-indigo-50 to-purple-50 border-indigo-100'}`}>
      <div className="flex items-start justify-between mb-4">
        <div>
          <p className="text-lg font-bold text-gray-900">{greet} 👋</p>
          <p className="text-sm text-gray-500 mt-0.5">
            {hasActions ? `Vous avez ${pendingOrders.length + (urgentMessages > 0 ? 1 : 0) + (lowStockCount > 0 ? 1 : 0)} point(s) à traiter` : 'Tout est à jour — belle journée !'}
          </p>
        </div>
        <span className="text-2xl">{hasActions ? '⚠️' : '✅'}</span>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {/* Commandes en attente */}
        <div className={`rounded-xl p-3 border ${pendingOrders.length > 0 ? 'bg-orange-50 border-orange-200' : 'bg-white border-gray-100'}`}>
          <p className="text-xs font-bold text-gray-400 uppercase mb-1">Commandes en attente</p>
          <p className={`text-2xl font-black ${pendingOrders.length > 0 ? 'text-orange-500' : 'text-gray-900'}`}>{pendingOrders.length}</p>
          {pendingOrders.length > 0 && (
            <div className="mt-2 space-y-1">
              {pendingOrders.slice(0, 2).map(o => (
                <div key={o.id} className="flex items-center justify-between">
                  <span className="text-xs text-gray-600">#{o.id} — {fmt(o.total_amount)}</span>
                  <button onClick={() => quickConfirm(o.id)}
                    className="text-[10px] font-bold text-white bg-orange-500 px-1.5 py-0.5 rounded-lg hover:bg-orange-600">
                    ✅ OK
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Messages urgents */}
        <div className={`rounded-xl p-3 border ${urgentMessages > 0 ? 'bg-red-50 border-red-200' : 'bg-white border-gray-100'}`}>
          <p className="text-xs font-bold text-gray-400 uppercase mb-1">Messages urgents</p>
          <p className={`text-2xl font-black ${urgentMessages > 0 ? 'text-red-500' : 'text-gray-900'}`}>{urgentMessages}</p>
          {urgentMessages > 0 && (
            <a href="/conversations" className="mt-2 block text-xs font-bold text-red-600 hover:underline">Voir les conversations →</a>
          )}
        </div>

        {/* Stock faible */}
        <div className={`rounded-xl p-3 border ${lowStockCount > 0 ? 'bg-yellow-50 border-yellow-200' : 'bg-white border-gray-100'}`}>
          <p className="text-xs font-bold text-gray-400 uppercase mb-1">Produits stock faible</p>
          <p className={`text-2xl font-black ${lowStockCount > 0 ? 'text-yellow-600' : 'text-gray-900'}`}>{lowStockCount}</p>
          {lowStockCount > 0 && (
            <p className="mt-2 text-xs text-yellow-700 truncate">{lowStock.slice(0, 2).map(p => p.name).join(', ')}</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// C. OBJECTIF CA MENSUEL
// ══════════════════════════════════════════════════════════════════════════════
function CaGoalWidget({ overview }) {
  const [goal, setGoal]         = useState(() => parseFloat(localStorage.getItem('ca_goal') || '5000'));
  const [editing, setEditing]   = useState(false);
  const [input, setInput]       = useState(goal);

  const current  = overview?.revenue?.current ?? 0;
  const pct      = goal > 0 ? Math.min((current / goal) * 100, 100) : 0;
  const overGoal = current >= goal;

  const now      = new Date();
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const daysDone = now.getDate();
  const projected = daysDone > 0 ? Math.round((current / daysDone) * daysInMonth) : 0;
  const projPct  = goal > 0 ? Math.round((projected / goal) * 100) : 0;

  const save = () => {
    const v = parseFloat(input) || goal;
    setGoal(v);
    localStorage.setItem('ca_goal', v.toString());
    setEditing(false);
  };

  const barColor = overGoal
    ? 'linear-gradient(90deg,#22c55e,#16a34a)'
    : pct >= 60
      ? 'linear-gradient(90deg,#6366f1,#3b82f6)'
      : 'linear-gradient(90deg,#f59e0b,#6366f1)';

  return (
    <div className="premium-card p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-xs font-bold text-gray-400 uppercase tracking-wide">🎯 Objectif CA mensuel</p>
          {editing ? (
            <div className="flex items-center gap-2 mt-1">
              <input type="number" value={input} onChange={e => setInput(e.target.value)}
                autoFocus onKeyDown={e => e.key === 'Enter' && save()}
                className="text-xl font-bold border border-gray-200 rounded-lg px-2 py-1 w-32 outline-none focus:border-indigo-400" />
              <span className="text-sm text-gray-400">{activeCurrency()}</span>
              <button onClick={save} className="bg-indigo-600 text-white px-3 py-1 rounded-lg text-sm font-medium">✓</button>
              <button onClick={() => setEditing(false)} className="text-gray-400 text-sm">✕</button>
            </div>
          ) : (
            <p className="text-xl font-bold text-gray-900 cursor-pointer mt-1 hover:text-indigo-600 transition-colors" onClick={() => { setEditing(true); setInput(goal); }}>
              {fmt(goal)} <span className="text-xs font-normal text-gray-400">cliquer pour modifier</span>
            </p>
          )}
        </div>
        <div className="text-right">
          <p className="text-xs font-bold text-gray-400 uppercase">CA actuel</p>
          <p className={`text-xl font-bold mt-1 ${overGoal ? 'text-green-600' : 'text-gray-900'}`}>{fmt(current)}</p>
        </div>
      </div>

      <div className="h-3 bg-gray-100 rounded-full overflow-hidden mb-2">
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: barColor }} />
      </div>

      <div className="flex justify-between items-center text-xs text-gray-500">
        <span>{pct.toFixed(0)}% atteint</span>
        <span className={projPct >= 100 ? 'text-green-600 font-semibold' : 'text-gray-400'}>
          Projection fin de mois : {fmt(projected)} ({projPct}%)
        </span>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// D. TOP 5 PRODUITS
// ══════════════════════════════════════════════════════════════════════════════
function TopProductsWidget({ api }) {
  const [products, setProducts] = useState([]);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    api.get('/analytics/top-products?limit=5').then(r => {
      setProducts(r.data?.products || r.data || []);
    }).catch(() => setProducts([])).finally(() => setLoading(false));
  }, [api]);

  if (loading) return (
    <div className="premium-card p-5 animate-pulse">
      <div className="h-4 bg-gray-100 rounded w-1/3 mb-4" />
      {[...Array(5)].map((_, i) => <div key={i} className="h-3 bg-gray-50 rounded mb-2" />)}
    </div>
  );

  if (!products.length) return null;

  const maxOrders = products[0]?.orders_count || 1;

  return (
    <div className="premium-card p-5">
      <p className="text-sm font-semibold text-gray-900 mb-4">🏆 Top produits — ce mois</p>
      <div className="space-y-3">
        {products.map((p, i) => (
          <div key={p.id || i} className="flex items-center gap-3">
            <span className={`text-xs font-black w-5 text-center ${i === 0 ? 'text-yellow-500' : i === 1 ? 'text-gray-400' : i === 2 ? 'text-amber-600' : 'text-gray-300'}`}>
              #{i + 1}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex justify-between items-center mb-0.5">
                <span className="text-xs font-semibold text-gray-800 truncate">{p.name}</span>
                <span className="text-xs font-bold text-indigo-600 ml-2 flex-shrink-0">{fmt(p.revenue || 0)}</span>
              </div>
              <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full rounded-full bg-indigo-400 transition-all" style={{ width: `${(p.orders_count / maxOrders) * 100}%` }} />
              </div>
              <p className="text-[10px] text-gray-400 mt-0.5">{p.orders_count ?? 0} commande(s)</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// E. WIDGET STOCK FAIBLE
// ══════════════════════════════════════════════════════════════════════════════
function LowStockWidget({ lowStock }) {
  const [expanded, setExpanded] = useState(false);
  if (!lowStock.length) return null;
  const shown = expanded ? lowStock : lowStock.slice(0, 4);

  return (
    <div className="bg-yellow-50 border border-yellow-200 rounded-2xl p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">⚠️</span>
          <p className="text-sm font-bold text-yellow-800">{lowStock.length} produit(s) en stock faible</p>
        </div>
        <a href="/products" className="text-xs font-bold text-yellow-700 border border-yellow-300 px-3 py-1 rounded-lg hover:bg-yellow-100">Gérer le stock →</a>
      </div>
      <div className="space-y-2">
        {shown.map((p, i) => (
          <div key={p.id || i} className="flex items-center justify-between bg-white rounded-xl px-3 py-2 border border-yellow-100">
            <div className="flex items-center gap-2 min-w-0">
              {p.image_url
                ? <img src={p.image_url} alt={p.name} className="w-8 h-8 rounded-lg object-cover flex-shrink-0" />
                : <div className="w-8 h-8 rounded-lg bg-yellow-100 flex items-center justify-center text-sm flex-shrink-0">📦</div>
              }
              <span className="text-xs font-semibold text-gray-800 truncate">{p.name}</span>
            </div>
            <span className={`text-xs font-black px-2 py-0.5 rounded-full flex-shrink-0 ${p.stock_qty === 0 ? 'bg-red-100 text-red-600' : 'bg-yellow-100 text-yellow-700'}`}>
              {p.stock_qty === 0 ? 'Rupture' : `${p.stock_qty} restant${p.stock_qty > 1 ? 's' : ''}`}
            </span>
          </div>
        ))}
      </div>
      {lowStock.length > 4 && (
        <button onClick={() => setExpanded(e => !e)} className="mt-3 text-xs font-bold text-yellow-700 hover:underline w-full text-center">
          {expanded ? 'Voir moins ▲' : `Voir ${lowStock.length - 4} de plus ▼`}
        </button>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// CREDIT WIDGET (inchangé)
// ══════════════════════════════════════════════════════════════════════════════
function CreditWidget({ api }) {
  const [usage, setUsage]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [showPacks, setShowPacks] = useState(false);
  const [packs, setPacks]     = useState([]);
  const toast = useToast();

  useEffect(() => {
    const load = async () => {
      try {
        const [usageRes, packsRes] = await Promise.allSettled([
          api.get('/billing/credits/usage'),
          api.get('/billing/credits/packs'),
        ]);
        if (usageRes.status === 'fulfilled') setUsage(usageRes.value.data);
        if (packsRes.status === 'fulfilled') setPacks(packsRes.value.data?.packs || []);
      } catch { /* silencieux */ }
      finally { setLoading(false); }
    };
    load();
  }, [api]);

  if (loading) return (
    <div className="premium-card p-5 animate-pulse">
      <div className="h-4 bg-gray-100 rounded w-1/3 mb-3" />
      <div className="h-3 bg-gray-100 rounded w-full mb-2" />
      <div className="h-3 bg-gray-100 rounded w-2/3" />
    </div>
  );

  if (!usage?.has_active_period) return null;

  const pct       = usage.usage_pct ?? 0;
  const isBlocked = usage.is_ai_blocked;
  const isNear    = pct >= 80 && !isBlocked;
  const barColor  = isBlocked
    ? 'linear-gradient(90deg,#ef4444,#dc2626)'
    : isNear ? 'linear-gradient(90deg,#f59e0b,#ef4444)'
    : 'linear-gradient(90deg,#6366f1,#3b82f6)';
  const bgCard = isBlocked ? 'bg-red-50 border-red-200' : isNear ? 'bg-amber-50 border-amber-200' : 'bg-white border-gray-100';

  const handleTopUp = async (packCode) => {
    try {
      await api.post('/billing/credits/top-up', { pack_code: packCode });
      const res = await api.get('/billing/credits/usage');
      setUsage(res.data);
      setShowPacks(false);
      toast.success('Recharge effectuée ! Crédits disponibles immédiatement.');
    } catch { toast.error('Erreur lors de la recharge. Vérifiez le paiement.'); }
  };

  return (
    <div className={`rounded-2xl border shadow-sm p-5 ${bgCard}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-lg">✦</span>
            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">Crédits IA</p>
            {isBlocked && <span className="text-xs font-bold bg-red-100 text-red-600 px-2 py-0.5 rounded-full">IA Bloquée</span>}
            {isNear && !isBlocked && <span className="text-xs font-bold bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">⚠ Bientôt épuisé</span>}
          </div>
          <p className="text-2xl font-bold text-gray-900">
            {(usage.ai_credits_remaining ?? 0).toLocaleString('fr-TN')}
            <span className="text-sm font-normal text-gray-400 ml-1">/ {(usage.ai_credits_allocated ?? 0).toLocaleString('fr-TN')} crédits</span>
          </p>
          <p className="text-xs text-gray-400 mt-0.5">{pct.toFixed(1)}% utilisés · Texte=1cr · Vocal=5cr · Image=10cr</p>
        </div>
        <button onClick={() => setShowPacks(!showPacks)}
          className="flex items-center gap-1.5 px-3 py-2 text-sm font-semibold bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 transition-colors flex-shrink-0">
          + Recharger
        </button>
      </div>
      <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden mb-1">
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.min(pct, 100)}%`, background: barColor }} />
      </div>
      <div className="flex justify-between text-xs text-gray-400">
        <span>0</span>
        <span>{(usage.ai_credits_allocated ?? 0).toLocaleString('fr-TN')} crédits</span>
      </div>
      {showPacks && packs.length > 0 && (
        <div className="mt-4 pt-4 border-t border-gray-100">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Recharges disponibles</p>
          <div className="grid grid-cols-3 gap-2">
            {packs.map(pack => (
              <button key={pack.pack_code} onClick={() => handleTopUp(pack.pack_code)}
                className="p-3 border border-gray-200 rounded-xl text-left hover:border-indigo-400 hover:bg-indigo-50 transition-all group">
                <p className="text-xs font-bold text-gray-900 group-hover:text-indigo-700">
                  {(pack.total_credits ?? pack.credits_amount).toLocaleString('fr-TN')} crédits
                  {pack.bonus_credits > 0 && <span className="ml-1 text-green-600">(+{pack.bonus_credits} bonus)</span>}
                </p>
                <p className="text-sm font-extrabold text-indigo-600 mt-1">{fmt(pack.price_dt)}</p>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// KPI CARD
// ══════════════════════════════════════════════════════════════════════════════
function KpiCard({ icon, label, value, sub, change, iconBg }) {
  return (
    <div className="bg-white rounded-2xl p-5 border border-gray-100 shadow-sm">
      <div className="flex items-start justify-between mb-3">
        <div className="p-2 rounded-xl text-xl" style={{ background: iconBg || '#f3f4f6' }}>{icon}</div>
        {change !== undefined && <span className={`text-xs font-semibold ${pctColor(change)}`}>{pctSign(change)}</span>}
      </div>
      <p className="text-2xl font-bold text-gray-900 leading-tight">{value}</p>
      <p className="text-sm text-gray-500 mt-1">{label}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// B. COMMANDES RÉCENTES avec actions rapides
// ══════════════════════════════════════════════════════════════════════════════
function RecentOrdersCard({ orders, api, onRefresh }) {
  const toast = useToast();

  const STATUS_COLORS = {
    pending:   'bg-yellow-100 text-yellow-700',
    confirmed: 'bg-blue-100 text-blue-700',
    paid:      'bg-green-100 text-green-700',
    shipped:   'bg-purple-100 text-purple-700',
    delivered: 'bg-emerald-100 text-emerald-700',
    cancelled: 'bg-red-100 text-red-700',
  };

  const STATUS_LABELS = {
    pending: 'En attente', confirmed: 'Confirmé', paid: 'Payé',
    shipped: 'Expédié', delivered: 'Livré', cancelled: 'Annulé',
  };

  const updateStatus = async (orderId, status) => {
    try {
      await api.put(`/orders/${orderId}/status`, { status });
      toast.success(`Commande #${orderId} → ${STATUS_LABELS[status] || status}`);
      onRefresh();
    } catch { toast.error('Erreur lors de la mise à jour'); }
  };

  return (
    <div className="premium-card overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-50 flex justify-between items-center">
        <h2 className="font-semibold text-gray-900 text-sm">Commandes récentes</h2>
        <a href="/orders" className="text-xs text-indigo-600 font-semibold hover:underline">Voir toutes →</a>
      </div>
      <div className="divide-y divide-gray-50">
        {orders.length === 0 ? (
          <p className="text-center text-gray-400 py-10 text-sm">Aucune commande pour le moment</p>
        ) : orders.map(o => (
          <div key={o.id} className="px-5 py-3">
            <div className="flex items-center justify-between mb-2">
              <div>
                <p className="text-sm font-semibold text-gray-900">Commande #{o.id}
                  {o.customer_name && <span className="text-gray-400 font-normal ml-1">· {o.customer_name}</span>}
                </p>
                <p className="text-xs text-gray-400">{new Date(o.created_at).toLocaleDateString('fr-TN', { day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit' })}</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold text-gray-900">{fmt(o.total_amount)}</p>
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_COLORS[o.status] || 'bg-gray-100 text-gray-600'}`}>
                  {STATUS_LABELS[o.status] || o.status}
                </span>
              </div>
            </div>
            {/* Actions rapides selon statut */}
            <div className="flex gap-2">
              {o.status === 'pending' && (
                <>
                  <button onClick={() => updateStatus(o.id, 'confirmed')}
                    className="flex-1 text-xs font-bold py-1.5 rounded-lg bg-blue-50 text-blue-700 border border-blue-200 hover:bg-blue-100 transition-colors">
                    ✅ Confirmer
                  </button>
                  <button onClick={() => updateStatus(o.id, 'cancelled')}
                    className="text-xs font-bold py-1.5 px-3 rounded-lg bg-red-50 text-red-600 border border-red-200 hover:bg-red-100 transition-colors">
                    ✕
                  </button>
                </>
              )}
              {o.status === 'confirmed' && (
                <button onClick={() => updateStatus(o.id, 'shipped')}
                  className="flex-1 text-xs font-bold py-1.5 rounded-lg bg-purple-50 text-purple-700 border border-purple-200 hover:bg-purple-100 transition-colors">
                  🚚 Marquer expédié
                </button>
              )}
              {o.status === 'shipped' && (
                <button onClick={() => updateStatus(o.id, 'delivered')}
                  className="flex-1 text-xs font-bold py-1.5 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 transition-colors">
                  ✅ Marquer livré
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// SPENDING TRACKER (inchangé, suppr via API)
// ══════════════════════════════════════════════════════════════════════════════
function SpendingTracker({ api }) {
  const { t } = useTranslation();
  const toast = useToast();
  const SPENDING_CATS_I18N = useSpendingCats();
  const catById_i18n = (id) => SPENDING_CATS_I18N.find(c => c.id === id) || SPENDING_CATS_I18N[5];
  const [expenses, setExpenses]         = useState([]);
  const [expensesLoading, setEL]        = useState(true);
  const [budget, setBudget]             = useState(4000);
  const [addOpen, setAddOpen]           = useState(false);
  const [scanOpen, setScanOpen]         = useState(false);
  const [scanning, setScanning]         = useState(false);
  const [editBudget, setEditBudget]     = useState(false);
  const [budgetInput, setBudgetInput]   = useState(budget);
  const [aiInsight, setAiInsight]       = useState('');
  const [insightLoading, setIL]         = useState(false);
  const [newExp, setNewExp]             = useState({ desc: '', cat: 'supplier', amount: '', date: new Date().toISOString().split('T')[0], vendor: '', note: '' });
  const [scannedInvoice, setScanned]    = useState(null);
  const fileRef = useRef();

  const totalSpent = expenses.reduce((s, e) => s + e.amount, 0);
  const remaining  = budget - totalSpent;
  const pct        = Math.min((totalSpent / budget) * 100, 100);
  const overBudget = totalSpent > budget;
  const byCat      = SPENDING_CATS_I18N.map(c => ({
    ...c, total: expenses.filter(e => e.cat === c.id).reduce((s, e) => s + e.amount, 0)
  })).filter(c => c.total > 0).sort((a, b) => b.total - a.total);

  const addExpense = async () => {
    if (!newExp.desc || !newExp.amount) return;
    try {
      const payload = { description: newExp.desc, category: newExp.cat, amount: parseFloat(newExp.amount), expense_date: newExp.date, vendor_name: newExp.vendor, notes: newExp.note };
      const resp = await api.post('expenses/', payload);
      const created = resp.data;
      setExpenses(prev => [{ id: created.id || Date.now(), desc: created.description || newExp.desc, cat: created.category || newExp.cat, amount: parseFloat(created.amount) || parseFloat(newExp.amount), date: created.expense_date || newExp.date, vendor: created.vendor_name || newExp.vendor, note: created.notes || newExp.note }, ...prev]);
    } catch {
      setExpenses(prev => [{ ...newExp, id: Date.now(), amount: parseFloat(newExp.amount) }, ...prev]);
    }
    setNewExp({ desc: '', cat: 'supplier', amount: '', date: new Date().toISOString().split('T')[0], vendor: '', note: '' });
    setAddOpen(false);
  };

  const deleteExpense = async (exp) => {
    try {
      if (exp.id && typeof exp.id === 'number' && exp.id < 1e12) {
        await api.delete(`expenses/${exp.id}`);
      }
    } catch { /* fallback: remove locally anyway */ }
    setExpenses(prev => prev.filter(e => e.id !== exp.id));
  };

  const scanInvoice = async (file) => {
    if (!file) return;
    setScanning(true);
    try {
      const toBase64 = (f) => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result.split(',')[1]); r.onerror = rej; r.readAsDataURL(f); });
      const b64  = await toBase64(file);
      const resp = await api.post('ai/scan-invoice', { image_base64: b64, media_type: file.type || 'image/jpeg' });
      const parsed = resp.data;
      setScanned(parsed);
      setNewExp({ desc: parsed.desc || '', vendor: parsed.vendor || '', amount: parsed.amount?.toString() || '', date: parsed.date || new Date().toISOString().split('T')[0], cat: parsed.cat || 'other', note: parsed.note || '' });
      setScanOpen(false); setAddOpen(true);
    } catch { toast.error(t('dashboard.scanError')); }
    finally   { setScanning(false); }
  };

  const getInsight = async () => {
    setIL(true);
    try {
      const top  = byCat.slice(0, 3).map(c => `${c.label}: ${fmt(c.total)}`).join(', ');
      const resp = await api.post('ai/spending-insight', { budget, total_spent: totalSpent, remaining, top_categories: top, expense_count: expenses.length });
      setAiInsight(resp.data?.insight || '');
    } catch { setAiInsight('Analyse IA indisponible.'); }
    finally   { setIL(false); }
  };

  useEffect(() => {
    const loadExpenses = async () => {
      setEL(true);
      try {
        const data = await api.get('expenses/');
        const items = Array.isArray(data.data) ? data.data : (data.data?.items || []);
        setExpenses(items.map(e => ({ id: e.id, desc: e.description || e.desc || '', cat: e.category || e.cat || 'other', amount: parseFloat(e.amount) || 0, date: e.date || e.expense_date || '', vendor: e.vendor_name || e.vendor || '', note: e.notes || e.note || '' })));
      } catch { setExpenses([]); }
      finally { setEL(false); }
    };
    loadExpenses();
    getInsight();
  }, []);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-900">{t('dashboard.spendingTracker')}</h2>
          <p className="text-sm text-gray-500">{t('dashboard.spendingSubtitle')}</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setScanOpen(true)}
            className="flex items-center gap-2 px-3 py-2 text-sm font-medium bg-violet-50 text-violet-700 border border-violet-200 rounded-xl hover:bg-violet-100 transition-colors">
            {t('dashboard.scanInvoice')}
          </button>
          <button onClick={() => setAddOpen(true)}
            className="flex items-center gap-2 px-3 py-2 text-sm font-medium bg-gray-900 text-white rounded-xl hover:bg-gray-700 transition-colors">
            {t('dashboard.add')}
          </button>
        </div>
      </div>

      <div className="premium-card p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">{t('dashboard.budget')}</p>
            {editBudget ? (
              <div className="flex gap-2 items-center mt-1">
                <input type="number" value={budgetInput} onChange={e => setBudgetInput(e.target.value)}
                  className="text-2xl font-bold border border-gray-200 rounded-lg px-2 py-1 w-32 outline-none focus:border-blue-400" autoFocus />
                <button onClick={() => { setBudget(parseFloat(budgetInput) || budget); setEditBudget(false); }}
                  className="bg-blue-600 text-white px-3 py-1 rounded-lg text-sm font-medium">{t('common.save')}</button>
              </div>
            ) : (
              <p className="text-2xl font-bold text-gray-900 cursor-pointer mt-1" onClick={() => { setEditBudget(true); setBudgetInput(budget); }}>
                {fmt(budget)} <span className="text-sm text-gray-400 font-normal">cliquer pour modifier</span>
              </p>
            )}
          </div>
          <div className="text-right">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">{t('dashboard.spent')}</p>
            <p className={`text-2xl font-bold mt-1 ${overBudget ? 'text-red-600' : 'text-gray-900'}`}>{fmt(totalSpent)}</p>
          </div>
        </div>
        <div className="h-3 bg-gray-100 rounded-full overflow-hidden mb-2">
          <div className="h-full rounded-full transition-all duration-700"
            style={{ width: `${pct}%`, background: overBudget ? 'linear-gradient(90deg,#f59e0b,#ef4444)' : 'linear-gradient(90deg,#6366f1,#22c55e)' }} />
        </div>
        <div className="flex justify-between items-center text-sm">
          <span className={overBudget ? 'text-red-500 font-medium' : 'text-green-600 font-medium'}>
            {overBudget ? `⚠ Dépassement de ${fmt(Math.abs(remaining))}` : `▼ Reste ${fmt(remaining)}`}
          </span>
          <span className="text-gray-400">{pct.toFixed(0)}% utilisé</span>
        </div>
      </div>

      <div className="bg-gradient-to-r from-violet-50 to-blue-50 border border-violet-100 rounded-2xl p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">✦</span>
            <span className="text-xs font-bold text-violet-700 uppercase tracking-wide">Analyse IA</span>
          </div>
          <button onClick={getInsight} disabled={insightLoading}
            className="text-xs text-violet-600 bg-white border border-violet-200 px-3 py-1 rounded-lg hover:bg-violet-50 disabled:opacity-50">
            {insightLoading ? '...' : '↺ Rafraîchir'}
          </button>
        </div>
        {insightLoading ? <div className="h-10 bg-white/60 rounded-lg animate-pulse" />
          : <p className="text-sm text-gray-700 leading-relaxed">{aiInsight || '...'}</p>}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="premium-card p-5">
          <p className="text-sm font-semibold text-gray-900 mb-4">{t('dashboard.byCategory')}</p>
          <div className="space-y-3">
            {byCat.map((c, i) => (
              <div key={i}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-gray-600">{c.label}</span>
                  <span className="font-semibold" style={{ color: c.color }}>{fmt(c.total)}</span>
                </div>
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${(c.total / totalSpent) * 100}%`, background: c.color }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="lg:col-span-2 premium-card overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50 flex justify-between items-center">
            <p className="font-semibold text-gray-900 text-sm">{t('dashboard.recentExpenses')}</p>
            <span className="text-xs text-gray-400">{expenses.length} entrées · {fmt(totalSpent)} total</span>
          </div>
          <div className="divide-y divide-gray-50 max-h-72 overflow-y-auto">
            {expenses.map(exp => {
              const cat = catById_i18n(exp.cat);
              return (
                <div key={exp.id} className="px-5 py-3 flex items-center gap-3 hover:bg-gray-50 group">
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center text-sm flex-shrink-0" style={{ background: cat.color + '18' }}>
                    {cat.label.split(' ')[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{exp.desc}</p>
                    <p className="text-xs text-gray-400">{exp.vendor && `${exp.vendor} · `}{new Date(exp.date).toLocaleDateString('fr-TN')}</p>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <p className="text-sm font-bold text-gray-900">{fmt(exp.amount)}</p>
                    <p className="text-xs" style={{ color: cat.color }}>{cat.label.split(' ').slice(1).join(' ')}</p>
                  </div>
                  <button onClick={() => deleteExpense(exp)}
                    className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-600 text-xs w-6 h-6 flex items-center justify-center rounded transition-all">✕</button>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {addOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={e => e.target === e.currentTarget && setAddOpen(false)}>
          <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <div className="flex justify-between items-center mb-5">
              <h3 className="font-bold text-gray-900 text-lg">{scannedInvoice ? '✅ Facture scannée' : t('dashboard.addExpense')}</h3>
              <button onClick={() => { setAddOpen(false); setScanned(null); }} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Description *</label>
                <input value={newExp.desc} onChange={e => setNewExp({ ...newExp, desc: e.target.value })}
                  className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm mt-1 outline-none focus:border-blue-400" placeholder="Ex: Achat textile" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Montant ({activeCurrency()}) *</label>
                  <input type="number" value={newExp.amount} onChange={e => setNewExp({ ...newExp, amount: e.target.value })}
                    className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm mt-1 outline-none focus:border-blue-400" placeholder="0.000" />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Date</label>
                  <input type="date" value={newExp.date} onChange={e => setNewExp({ ...newExp, date: e.target.value })}
                    className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm mt-1 outline-none focus:border-blue-400" />
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Fournisseur</label>
                <input value={newExp.vendor} onChange={e => setNewExp({ ...newExp, vendor: e.target.value })}
                  className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm mt-1 outline-none focus:border-blue-400" placeholder="Nom du fournisseur" />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Catégorie</label>
                <div className="flex flex-wrap gap-2 mt-2">
                  {SPENDING_CATS.map(c => (
                    <button key={c.id} onClick={() => setNewExp({ ...newExp, cat: c.id })}
                      className="px-3 py-1.5 rounded-lg text-xs font-medium border transition-all"
                      style={newExp.cat === c.id ? { background: c.color + '20', color: c.color, borderColor: c.color + '40' } : { background: '#f9fafb', color: '#6b7280', borderColor: '#e5e7eb' }}>
                      {c.label}
                    </button>
                  ))}
                </div>
              </div>
              <button onClick={addExpense} className="w-full bg-gray-900 text-white py-3 rounded-xl font-semibold text-sm hover:bg-gray-700 transition-colors">
                Enregistrer la dépense
              </button>
            </div>
          </div>
        </div>
      )}

      {scanOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={e => e.target === e.currentTarget && setScanOpen(false)}>
          <div className="bg-white rounded-2xl p-6 w-full max-w-sm shadow-2xl text-center">
            <div className="text-4xl mb-3">📄</div>
            <h3 className="font-bold text-gray-900 text-lg mb-2">{t('dashboard.scanTitle')}</h3>
            <p className="text-sm text-gray-500 mb-5">{t('dashboard.scanDesc')}</p>
            <input ref={fileRef} type="file" accept="image/*,application/pdf" className="hidden"
              onChange={e => { if (e.target.files[0]) scanInvoice(e.target.files[0]); }} />
            {scanning ? (
              <div className="flex flex-col items-center gap-3 py-4">
                <div className="animate-spin text-3xl">⏳</div>
                <p className="text-sm text-violet-600 font-medium">{t('dashboard.scanning')}</p>
              </div>
            ) : (
              <div className="space-y-3">
                <button onClick={() => fileRef.current?.click()}
                  className="w-full bg-violet-600 text-white py-3 rounded-xl font-semibold text-sm hover:bg-violet-700 transition-colors">
                  📁 {t('dashboard.scanBtn')}
                </button>
                <button onClick={() => setScanOpen(false)} className="w-full text-gray-500 text-sm">{t('common.cancel')}</button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// MAIN DASHBOARD
// ══════════════════════════════════════════════════════════════════════════════
export default function Dashboard() {
  const { api, store } = useStore();
  activeStoreConfig = store;
  const { t }   = useTranslation();
  const PERIOD_OPTS_I18N = usePeriodOpts();
  const [tab, setTab]             = useState('overview');
  const [period, setPeriod]       = useState('30d');
  const [overview, setOverview]   = useState(null);
  const [sales, setSales]         = useState(null);
  const [channels, setChannels]   = useState(null);
  const [customers, setCustomers] = useState(null);
  const [sentiment, setSentiment] = useState(null);
  const [posts, setPosts]         = useState(null);
  const [recentOrders, setRecentOrders] = useState([]);
  const [lowStock, setLowStock]   = useState([]);
  const [loading, setLoading]     = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ovRes, ordRes, chRes, custRes, sentRes, postsRes, stockRes] = await Promise.allSettled([
        api.get('/analytics/overview'),
        api.get('/orders/?limit=6'),
        api.get('/analytics/channels?days=30'),
        api.get('/analytics/customers?days=30'),
        api.get('/analytics/sentiment?days=30'),
        api.get('/analytics/posts'),
        api.get('/products/?low_stock=true&limit=20'),
      ]);
      if (ovRes.status    === 'fulfilled') setOverview(ovRes.value.data);
      if (ordRes.status   === 'fulfilled') setRecentOrders(ordRes.value.data.items || []);
      if (chRes.status    === 'fulfilled') setChannels(chRes.value.data);
      if (custRes.status  === 'fulfilled') setCustomers(custRes.value.data);
      if (sentRes.status  === 'fulfilled') setSentiment(sentRes.value.data);
      if (postsRes.status === 'fulfilled') setPosts(postsRes.value.data);
      if (stockRes.status === 'fulfilled') {
        const items = stockRes.value.data?.items || stockRes.value.data || [];
        setLowStock(items.filter(p => (p.stock_qty ?? p.stock ?? 0) <= 5));
      }
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [api]);

  const loadSales = useCallback(async (p) => {
    try { const r = await api.get(`/analytics/sales?period=${p}`); setSales(r.data); } catch {}
  }, [api]);

  useEffect(() => { load(); },         [load]);
  useEffect(() => { loadSales(period);}, [period, loadSales]);

  const STATUS_COLORS = {
    pending: 'bg-yellow-100 text-yellow-700', confirmed: 'bg-blue-100 text-blue-700',
    paid: 'bg-green-100 text-green-700', shipped: 'bg-purple-100 text-purple-700',
    delivered: 'bg-emerald-100 text-emerald-700', cancelled: 'bg-red-100 text-red-700',
  };

  const TABS = [
    { id: 'overview',  label: '⬡ ' + t('dashboard.title') },
    { id: 'analytics', label: '📈 Analytics' },
    { id: 'spending',  label: t('dashboard.spendingTracker') },
  ];

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center">
        <div className="animate-spin text-4xl mb-3">⏳</div>
        <p className="text-gray-500 text-sm">{t('common.loading')}</p>
      </div>
    </div>
  );

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">{t('dashboard.title')}</h1>
        <button onClick={load} className="text-sm text-gray-500 hover:text-gray-700 flex items-center gap-1.5 border border-gray-200 rounded-xl px-3 py-1.5 hover:bg-gray-50 transition-colors">
          ↺ {t('dashboard.refreshInsight')}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 bg-gray-100 p-1 rounded-xl w-fit">
        {TABS.map(t2 => (
          <button key={t2.id} onClick={() => setTab(t2.id)}
            className={`px-4 py-2 text-sm font-medium rounded-lg transition-all ${tab === t2.id ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
            {t2.label}
          </button>
        ))}
      </div>

      {/* ── TAB: VUE GÉNÉRALE ── */}
      {tab === 'overview' && (
        <div className="space-y-5">
          {/* A. Morning Brief */}
          <MorningBrief overview={overview} recentOrders={recentOrders} lowStock={lowStock} api={api} onRefresh={load} />

          {/* Widget crédits */}
          <CreditWidget api={api} />

          {/* KPIs + Objectif CA */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard icon="💰" label={`CA ce mois (${activeCurrency()})`} value={fmt(overview?.revenue?.current)} change={overview?.revenue?.change_pct} iconBg="#eff6ff" />
            <KpiCard icon="📦" label="Commandes" value={overview?.orders?.current ?? '—'} change={overview?.orders?.change_pct} sub={`vs ${overview?.orders?.previous ?? 0} mois préc.`} iconBg="#fdf4ff" />
            <KpiCard icon="👥" label="Clients total" value={overview?.customers?.total ?? '—'} sub={`+${overview?.customers?.new_30d ?? 0} nouveaux ce mois`} iconBg="#f0fdf4" />
            <KpiCard icon="💬" label="Messages 30j" value={fmtShort(overview?.messages?.total_30d)} sub="Toutes canaux confondus" iconBg="#fff7ed" />
          </div>

          {/* C. Objectif CA mensuel */}
          <CaGoalWidget overview={overview} />

          {/* E. Stock faible */}
          <LowStockWidget lowStock={lowStock} />

          {/* B. Commandes récentes avec actions + D. Top produits */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2">
              <RecentOrdersCard orders={recentOrders} api={api} onRefresh={load} />
            </div>
            <TopProductsWidget api={api} />
          </div>

          {/* Canaux + Sentiment */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="premium-card p-5">
              <h2 className="font-semibold text-gray-900 text-sm mb-4">Messages par canal (30j)</h2>
              {channels?.channels?.length ? (
                <div className="space-y-3">
                  {channels.channels.map((c, i) => {
                    const meta = CH_META[c.channel] || {};
                    return (
                      <div key={i}>
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <span className="text-base">{meta.icon || '💬'}</span>
                            <span className="text-sm font-medium text-gray-700">{meta.name || c.channel}</span>
                          </div>
                          <div className="text-right">
                            <span className="text-sm font-bold text-gray-900">{fmtShort(c.messages)}</span>
                            <span className="text-xs text-gray-400 ml-1">{c.pct}%</span>
                          </div>
                        </div>
                        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                          <div className="h-full rounded-full transition-all" style={{ width: `${c.pct}%`, background: meta.color || '#6366f1' }} />
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">{c.customers} clients uniques</p>
                      </div>
                    );
                  })}
                </div>
              ) : <p className="text-gray-400 text-sm text-center py-8">Pas encore de données canaux</p>}
            </div>

            <div className="premium-card p-5">
              <h2 className="font-semibold text-gray-900 text-sm mb-4">😊 Analyse sentiment clients</h2>
              {sentiment?.has_real_data && sentiment?.distribution ? (
                <div className="space-y-3">
                  {[
                    { k: 'positive', label: '😊 Positif', color: '#22c55e' },
                    { k: 'neutral',  label: '😐 Neutre',  color: '#94a3b8' },
                    { k: 'negative', label: '😤 Négatif', color: '#f97316' },
                    { k: 'urgent',   label: '🚨 Urgent',  color: '#ef4444' },
                  ].map(({ k, label, color }) => {
                    const d = sentiment.distribution[k] || { count: 0, pct: 0 };
                    return (
                      <div key={k}>
                        <div className="flex justify-between text-xs mb-1">
                          <span className="text-gray-600">{label}</span>
                          <span className="font-semibold" style={{ color }}>{d.pct}%</span>
                        </div>
                        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                          <div className="h-full rounded-full transition-all" style={{ width: `${d.pct}%`, background: color }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                // P1.12-FIX : ne plus jamais afficher un graphique avec des
                // pourcentages inventés. Message honnête tant qu'aucune
                // conversation n'a reçu d'analyse de sentiment réelle.
                <p className="text-gray-400 text-sm text-center py-8">
                  Pas encore assez de conversations analysées pour ce store.
                </p>
              )}
            </div>
          </div>

          {/* Clients */}
          {customers && (
            <div className="premium-card p-5">
              <h2 className="font-semibold text-gray-900 text-sm mb-4">👥 Analyse clients</h2>
              <div className="grid grid-cols-3 gap-3 mb-4">
                {[
                  { label: 'Total', value: customers.total, color: '#6366f1' },
                  { label: 'Acheteurs', value: customers.buyers, color: '#22c55e' },
                  { label: 'Prospects', value: customers.prospects, color: '#f59e0b' },
                ].map((s, i) => (
                  <div key={i} className="text-center p-3 rounded-xl" style={{ background: s.color + '12' }}>
                    <p className="text-xl font-bold" style={{ color: s.color }}>{s.value}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{s.label}</p>
                  </div>
                ))}
              </div>
              {customers.top_customers?.length > 0 && (
                <div className="border-t border-gray-50 pt-3">
                  <p className="text-xs font-medium text-gray-500 mb-2">Top clients</p>
                  {customers.top_customers.slice(0, 3).map((c, i) => (
                    <div key={i} className="flex justify-between items-center py-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400">#{i + 1}</span>
                        <span className="text-xs text-gray-700 truncate max-w-28">{c.name}</span>
                        <span className="text-xs" style={{ color: CH_META[c.channel]?.color || '#6b7280' }}>{CH_META[c.channel]?.icon || '💬'}</span>
                      </div>
                      <span className="text-xs font-bold text-gray-900">{fmt(c.total_spent)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Réseaux sociaux */}
          {posts?.channels && (
            <div className="premium-card p-5">
              <div className="flex items-center justify-between mb-4">
                <h2 className="font-semibold text-gray-900 text-sm">📱 Vues & impressions — Réseaux sociaux</h2>
                <span className="text-xs text-gray-400 bg-gray-50 px-2 py-1 rounded-lg">{posts.note}</span>
              </div>
              <div className="grid grid-cols-3 gap-4">
                {Object.entries(posts.channels).map(([ch, d]) => {
                  const meta = CH_META[ch] || {};
                  return (
                    <div key={ch} className="rounded-xl p-4 border" style={{ borderColor: meta.color + '30', background: meta.color + '08' }}>
                      <div className="flex items-center gap-2 mb-3">
                        <span className="text-xl">{meta.icon || '📱'}</span>
                        <span className="font-semibold text-sm" style={{ color: meta.color }}>{meta.name || ch}</span>
                      </div>
                      <div className="space-y-1.5 text-xs">
                        {d.total_views !== undefined && <div className="flex justify-between"><span className="text-gray-500">👁 Vues</span><span className="font-bold">{fmtShort(d.total_views)}</span></div>}
                        {d.total_likes !== undefined && <div className="flex justify-between"><span className="text-gray-500">❤️ Likes</span><span className="font-bold">{fmtShort(d.total_likes)}</span></div>}
                        {d.total_dms  !== undefined && <div className="flex justify-between"><span className="text-gray-500">💬 DMs</span><span className="font-bold text-green-600">{d.total_dms}</span></div>}
                        {d.avg_engagement_rate !== undefined && <div className="flex justify-between"><span className="text-gray-500">📊 Engage.</span><span className="font-bold text-blue-600">{d.avg_engagement_rate}%</span></div>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* CTA Publication IA */}
          <div className="bg-gradient-to-r from-violet-600 to-pink-500 rounded-2xl p-5 text-white">
            <div className="flex flex-col sm:flex-row sm:items-center gap-4">
              <div className="flex-1">
                <p className="font-bold text-base">📣 Publication IA — Réseaux Sociaux</p>
                <p className="text-violet-100 text-xs sm:text-sm mt-1">GPT-4o génère vos annonces · DALL-E 3 crée vos visuels · Publication automatique multi-réseau</p>
              </div>
              <a href="/social-broadcast" className="flex-shrink-0 bg-white text-violet-700 font-bold rounded-xl px-4 py-2.5 text-sm hover:bg-violet-50 transition text-center">
                🚀 Publier maintenant →
              </a>
            </div>
          </div>
        </div>
      )}

      {/* ── TAB: ANALYTICS ── */}
      {tab === 'analytics' && (
        <div className="space-y-5">
          <div className="flex gap-2 flex-wrap">
            {PERIOD_OPTS_I18N.map(p => (
              <button key={p.v} onClick={() => setPeriod(p.v)}
                className={`px-3 py-1.5 text-sm font-medium rounded-lg border transition-all ${period === p.v ? 'bg-gray-900 text-white border-gray-900' : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400'}`}>
                {p.l}
              </button>
            ))}
          </div>
          <div className="premium-card p-5">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-semibold text-gray-900 text-sm">Ventes — {PERIOD_OPTS_I18N.find(p2 => p2.v === period)?.l}</h2>
              <div className="flex gap-4 text-xs text-gray-500">
                <span>CA total : <strong className="text-gray-900">{fmt(sales?.totals?.revenue)}</strong></span>
                <span>Commandes : <strong className="text-gray-900">{sales?.totals?.orders ?? 0}</strong></span>
                <span>Panier moy. : <strong className="text-gray-900">{fmt(sales?.totals?.avg_order_value)}</strong></span>
              </div>
            </div>
            {sales?.data?.length ? (
              <div>
                <MiniBar data={sales.data} valueKey="revenue" labelKey="label" color="#6366f1" height={100} />
                <div className="flex justify-between mt-2">
                  <span className="text-xs text-gray-400">{sales.data[0]?.label}</span>
                  <span className="text-xs text-gray-400">{sales.data[sales.data.length - 1]?.label}</span>
                </div>
              </div>
            ) : <div className="h-24 flex items-center justify-center text-gray-300 text-sm">Pas encore de ventes sur cette période</div>}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="premium-card p-5">
              <h2 className="font-semibold text-gray-900 text-sm mb-4">📦 Commandes par période</h2>
              {sales?.data?.length ? <MiniBar data={sales.data} valueKey="orders" labelKey="label" color="#22c55e" height={80} />
                : <div className="h-20 flex items-center justify-center text-gray-300 text-sm">Pas de données</div>}
            </div>
            <div className="premium-card p-5">
              <h2 className="font-semibold text-gray-900 text-sm mb-4">📊 Répartition clients par canal</h2>
              {customers?.by_channel && Object.keys(customers.by_channel).length ? (
                <div className="space-y-2">
                  {Object.entries(customers.by_channel).map(([ch, n]) => {
                    const meta = CH_META[ch] || {};
                    const total_c = Object.values(customers.by_channel).reduce((s, v) => s + v, 0) || 1;
                    return (
                      <div key={ch} className="flex items-center gap-3">
                        <span className="text-sm w-5">{meta.icon || '💬'}</span>
                        <div className="flex-1">
                          <div className="flex justify-between text-xs mb-0.5">
                            <span className="text-gray-600">{meta.name || ch}</span>
                            <span className="font-semibold">{n}</span>
                          </div>
                          <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${n / total_c * 100}%`, background: meta.color || '#6366f1' }} />
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : <p className="text-gray-400 text-sm text-center py-6">Pas de données</p>}
            </div>
          </div>
        </div>
      )}

      {/* ── TAB: SPENDING ── */}
      {tab === 'spending' && <SpendingTracker api={api} />}
    </div>
  );
}
