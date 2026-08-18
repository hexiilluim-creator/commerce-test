// src/pages/SuperAdmin.jsx — AutoCommerce SaaS Maghreb
// Onglets : Boutiques | Abonnements | Crédits IA | Statistiques
import React, { useState, useEffect, useCallback } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, Cell, PieChart, Pie,
} from 'recharts';
import { useStore } from '../context/StoreContext';
import { useToast } from '../context/ToastContext';

// ── Plans Maghreb ───────────────────────────────────────────────────────────
const PLAN_OPTIONS = [
  { value: 'starter',      label: 'Starter',      monthly: 19.99, color: '#6366f1' },
  { value: 'business',     label: 'Business',     monthly: 29.99, color: '#0ea5e9' },
  { value: 'premium',      label: 'Premium',      monthly: 39.99, color: '#8b5cf6' },
  { value: 'pro_whatsapp', label: 'Pro WhatsApp', monthly: 59.99, color: '#25D366' },
  { value: 'enterprise',   label: 'Enterprise',   monthly: 99.99, color: '#111827' },
  { value: 'gold',         label: 'Gold',         monthly: 149.99, color: '#d97706' },
];
const PLAN_META = Object.fromEntries(PLAN_OPTIONS.map(p => [p.value, p]));
const PLAN_COLORS = {
  starter: '#6366f1', business: '#0ea5e9',
  premium: '#8b5cf6', pro_whatsapp: '#25D366',
};

// ── Prix par durée (DT) ─────────────────────────────────────────────────────
const DURATION_PRICING = {
  starter:      { 3: 59,  6: 97,  12: 199 },
  business:     { 3: 89,  6: 145, 12: 299 },
  premium:      { 3: 119, 6: 195, 12: 399 },
  pro_whatsapp: { 3: 179, 6: 290, 12: 599 },
  enterprise:   { 3: 299, 6: 489, 12: 999 },
  gold:         { 3: 449, 6: 734, 12: 1499 },
};

const DURATION_OPTIONS = [
  { months: 3,  label: '3 mois',  discount: '',           badge: '' },
  { months: 6,  label: '6 mois',  discount: '~10% remise',badge: '1 mois offert' },
  { months: 12, label: '12 mois', discount: '~17% remise',badge: '2 mois offerts' },
];

const getPriceDT = (plan, months) => DURATION_PRICING[plan]?.[months] || 0;
const getMonthlyEquiv = (plan, months) => (getPriceDT(plan, months) / months).toFixed(2);

// ── Helpers ─────────────────────────────────────────────────────────────────
const fmtDate = d => d ? new Date(d).toLocaleDateString('fr-TN') : '—';
const fmtNum  = n => (n || 0).toLocaleString('fr-TN');

function daysRemaining(expiresAt) {
  if (!expiresAt) return null;
  const diff = new Date(expiresAt) - new Date();
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

// ── Composants communs ───────────────────────────────────────────────────────
function PlanBadge({ code }) {
  const m = PLAN_META[code] || { label: code || 'Inconnu', color: '#9ca3af' };
  return (
    <span style={{
      background: m.color + '18', color: m.color,
      border: `1px solid ${m.color}40`,
      padding: '2px 10px', borderRadius: 20, fontSize: 12, fontWeight: 700,
    }}>
      {m.label}
    </span>
  );
}

function StatusBadge({ status, daysLeft }) {
  let cfg;
  if (status === 'active' && daysLeft !== null && daysLeft <= 1)
    cfg = { bg: '#fff7ed', color: '#c2410c', label: '⛔ Expire demain' };
  else if (status === 'active' && daysLeft !== null && daysLeft <= 7)
    cfg = { bg: '#fef9c3', color: '#a16207', label: `⚠️ Expire J-${daysLeft}` };
  else cfg = {
    active:    { bg: '#ecfdf5', color: '#065f46', label: 'Actif' },
    expired:   { bg: '#fef9c3', color: '#713f12', label: 'Expiré' },
    suspended: { bg: '#fef2f2', color: '#7f1d1d', label: 'Suspendu' },
    cancelled: { bg: '#f3f4f6', color: '#374151', label: 'Annulé' },
    trialing:  { bg: '#eff6ff', color: '#1e40af', label: 'Essai' },
  }[status] || { bg: '#f3f4f6', color: '#374151', label: status || '—' };
  return (
    <span style={{ background: cfg.bg, color: cfg.color, padding: '2px 10px', borderRadius: 20, fontSize: 12, fontWeight: 600 }}>
      {cfg.label}
    </span>
  );
}

function ReminderDot({ sent }) {
  return (
    <span style={{
      display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
      background: sent ? '#10b981' : '#e5e7eb',
      border: sent ? '2px solid #059669' : '2px solid #d1d5db',
      flexShrink: 0,
    }} title={sent ? `Envoyé le ${fmtDate(sent)}` : 'Non envoyé'} />
  );
}

function ProgressBar({ pct, blocked }) {
  const color = blocked
    ? 'linear-gradient(90deg,#ef4444,#dc2626)'
    : pct >= 80
      ? 'linear-gradient(90deg,#f59e0b,#ef4444)'
      : 'linear-gradient(90deg,#6366f1,#3b82f6)';
  return (
    <div style={{ background: '#f3f4f6', borderRadius: 6, height: 8, width: 120, overflow: 'hidden' }}>
      <div style={{ height: '100%', borderRadius: 6, background: color, width: `${Math.min(pct, 100)}%`, transition: 'width .4s' }} />
    </div>
  );
}

function Loader() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
      <div style={{ width: 28, height: 28, border: '3px solid #e5e7eb', borderTopColor: '#6366f1', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}

function Card({ title, action, children, noPad }) {
  return (
    <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #e5e7eb', boxShadow: '0 1px 4px rgba(0,0,0,0.04)', overflow: 'hidden' }}>
      {title !== undefined && (
        <div style={{ padding: '16px 24px', borderBottom: '1px solid #f3f4f6', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <h3 style={{ fontWeight: 700, fontSize: 15, color: '#111827', margin: 0 }}>{title}</h3>
          {action}
        </div>
      )}
      <div style={noPad ? {} : { padding: 24 }}>{children}</div>
    </div>
  );
}

function KpiCard({ label, value, sub, color, alert }) {
  return (
    <div style={{
      background: alert ? '#fef2f2' : '#fff',
      border: `1px solid ${alert ? '#fecaca' : '#e5e7eb'}`,
      borderRadius: 14, padding: '18px 22px', boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
    }}>
      <p style={{ fontSize: 12, fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>{label}</p>
      <p style={{ fontSize: 26, fontWeight: 800, color: color || '#111827', margin: 0 }}>{value}</p>
      {sub && <p style={{ fontSize: 12, color: '#9ca3af', marginTop: 4 }}>{sub}</p>}
    </div>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────
const btnPrimary = { background: '#4f46e5', color: '#fff', border: 'none', borderRadius: 10, padding: '10px 20px', fontWeight: 700, fontSize: 14, cursor: 'pointer' };
const btnDanger  = { background: '#fef2f2', color: '#dc2626', border: '1px solid #fecaca', borderRadius: 8, padding: '5px 12px', fontSize: 12, fontWeight: 700, cursor: 'pointer' };
const btnGhost   = { background: 'transparent', color: '#6b7280', border: '1px solid #e5e7eb', borderRadius: 8, padding: '6px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer' };
const btnSmall   = { background: '#4f46e5', color: '#fff', border: 'none', borderRadius: 8, padding: '8px 16px', fontWeight: 700, fontSize: 13, cursor: 'pointer' };
const btnSuccess = { background: '#059669', color: '#fff', border: 'none', borderRadius: 8, padding: '8px 16px', fontWeight: 700, fontSize: 13, cursor: 'pointer' };
const inputStyle = { border: '1px solid #e5e7eb', borderRadius: 8, padding: '8px 12px', fontSize: 13, outline: 'none', width: '100%', boxSizing: 'border-box' };
const selectStyle = { ...inputStyle, cursor: 'pointer', background: '#fff' };
const labelStyle = { display: 'block', fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 6 };

// ══════════════════════════════════════════════════════════════════════════════
// TAB 1 — Boutiques & Plans
// ══════════════════════════════════════════════════════════════════════════════
function TabStores({ api }) {
  const [stores, setStores]   = useState([]);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  const fetchStores = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/super-admin/stores');
      // FIX: backend returns PaginatedStores {items, total, page} not a bare array
      const data = res.data;
      setStores(Array.isArray(data) ? data : (data?.items || []));
    } catch { toast.error('Impossible de charger les boutiques'); }
    finally   { setLoading(false); }
  }, [api]);

  useEffect(() => { fetchStores(); }, [fetchStores]);

  const updatePlan = async (storeId, planCode) => {
    try {
      await api.put(`/super-admin/stores/${storeId}/subscription`, { plan_code: planCode, days: 30 });
      fetchStores();
      toast.success('Plan mis à jour');
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Erreur mise à jour plan');
    }
  };

  if (loading) return <Loader />;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <p style={{ color: '#6b7280', fontSize: 14 }}>{stores.length} boutique{stores.length > 1 ? 's' : ''}</p>
        <button onClick={fetchStores} style={btnGhost}>↺ Actualiser</button>
      </div>
      <Card noPad>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead style={{ background: '#f9fafb', borderBottom: '1px solid #f3f4f6' }}>
              <tr>
                {['Boutique', 'Email admin', 'Plan', 'Paiement', 'Statut', 'Expire le', 'Features'].map(h => (
                  <th key={h} style={{ padding: '12px 20px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stores.map((store, i) => (
                <tr key={store.id} style={{ borderTop: i ? '1px solid #f3f4f6' : 'none' }}
                    onMouseEnter={e => e.currentTarget.style.background = '#fafafa'}
                    onMouseLeave={e => e.currentTarget.style.background = ''}>
                  <td style={{ padding: '14px 20px', fontWeight: 600, color: '#111827' }}>{store.name}</td>
                  <td style={{ padding: '14px 20px', color: '#6b7280' }}>{store.admin_email}</td>
                  <td style={{ padding: '14px 20px' }}>
                    <select
                      value={store.plan_code || 'starter'}
                      onChange={e => updatePlan(store.id, e.target.value)}
                      style={{ fontSize: 13, border: '1px solid #e5e7eb', borderRadius: 8, padding: '4px 8px', background: '#fff', cursor: 'pointer' }}
                    >
                      {PLAN_OPTIONS.map(p => (
                        <option key={p.value} value={p.value}>{p.label} — {p.monthly} DT/mois</option>
                      ))}
                    </select>
                  </td>
                  <td style={{ padding: '14px 20px' }}>
                    <span style={{
                      padding: '2px 10px', borderRadius: 20, fontSize: 12, fontWeight: 700,
                      background: store.is_paid ? '#ecfdf5' : '#f3f4f6',
                      color: store.is_paid ? '#065f46' : '#6b7280',
                    }}>
                      {store.is_paid ? 'PAYANT' : 'GRATUIT'}
                    </span>
                  </td>
                  <td style={{ padding: '14px 20px' }}>
                    <StatusBadge status={store.status} daysLeft={daysRemaining(store.expires_at)} />
                  </td>
                  <td style={{ padding: '14px 20px', color: '#9ca3af', fontSize: 13 }}>{fmtDate(store.expires_at)}</td>
                  <td style={{ padding: '14px 20px', maxWidth: 280 }}>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {(store.features || []).slice(0, 5).map(f => (
                        <span key={f} style={{ padding: '2px 8px', borderRadius: 10, background: '#eff6ff', color: '#1d4ed8', fontSize: 11 }}>{f}</span>
                      ))}
                      {(store.features || []).length > 5 && (
                        <span style={{ padding: '2px 8px', borderRadius: 10, background: '#f3f4f6', color: '#6b7280', fontSize: 11 }}>+{store.features.length - 5}</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {!stores.length && (
                <tr><td colSpan={7} style={{ padding: 48, textAlign: 'center', color: '#9ca3af' }}>Aucune boutique enregistrée</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 2 — Abonnements (nouveau)
// ══════════════════════════════════════════════════════════════════════════════
function TabSubscriptions({ api }) {
  const toast = useToast();

  // Liste abonnements
  const [subs, setSubs]       = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter]   = useState('all');     // all | active | expired | expiring

  // Formulaire création
  const [showForm, setShowForm]   = useState(false);
  const [formStoreId, setFormStoreId]     = useState('');
  const [formPlan, setFormPlan]           = useState('starter');
  const [formDuration, setFormDuration]   = useState(3);
  const [formNotes, setFormNotes]         = useState('');
  const [formLoading, setFormLoading]     = useState(false);

  // Actions système
  const [blockLoading, setBlockLoading]       = useState(false);
  const [reminderLoading, setReminderLoading] = useState(false);

  const fetchSubs = useCallback(async () => {
    setLoading(true);
    try {
      const params = filter === 'expiring'
        ? '?expiring_days=7'
        : filter !== 'all' ? `?status=${filter}` : '';
      const res = await api.get(`/super-admin/subscriptions${params}`);
      setSubs(Array.isArray(res.data) ? res.data : (res.data?.items || []));
    } catch { toast.error('Impossible de charger les abonnements'); }
    finally   { setLoading(false); }
  }, [api, filter]);

  useEffect(() => { fetchSubs(); }, [fetchSubs]);

  const priceDT = getPriceDT(formPlan, formDuration);
  const monthlyEquiv = getMonthlyEquiv(formPlan, formDuration);

  const handleCreate = async () => {
    if (!formStoreId) { toast.error('ID boutique requis'); return; }
    setFormLoading(true);
    try {
      const res = await api.post(`/super-admin/stores/${formStoreId}/subscriptions`, {
        plan_code: formPlan,
        duration_months: formDuration,
        notes: formNotes || null,
      });
      toast.success(`✅ Abonnement ${formPlan} — ${formDuration} mois créé (${priceDT} DT)`);
      setShowForm(false);
      setFormStoreId(''); setFormNotes('');
      fetchSubs();
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Erreur création abonnement');
    } finally { setFormLoading(false); }
  };

  const handleBlockExpired = async () => {
    setBlockLoading(true);
    try {
      const res = await api.post('/super-admin/subscriptions/check-expired');
      toast.success(`${res.data.blocked} boutique(s) bloquée(s)`);
      fetchSubs();
    } catch { toast.error('Erreur lors du blocage'); }
    finally { setBlockLoading(false); }
  };

  const handleReminders = async () => {
    setReminderLoading(true);
    try {
      const res = await api.post('/super-admin/subscriptions/send-reminders');
      toast.success(`Rappels envoyés — J-7: ${res.data.reminders_7d_sent} | J-1: ${res.data.reminders_1d_sent}`);
    } catch { toast.error('Erreur rappels'); }
    finally { setReminderLoading(false); }
  };

  // KPIs rapides
  const kpis = {
    total:    subs.length,
    active:   subs.filter(s => s.status === 'active').length,
    expiring: subs.filter(s => s.status === 'active' && s.days_remaining <= 7).length,
    expired:  subs.filter(s => s.status === 'expired').length,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <KpiCard label="Total abonnements" value={kpis.total} color="#4f46e5" />
        <KpiCard label="Actifs" value={kpis.active} color="#10b981" />
        <KpiCard label="Expirent dans 7j" value={kpis.expiring} color="#f59e0b" alert={kpis.expiring > 0} />
        <KpiCard label="Expirés" value={kpis.expired} color="#ef4444" alert={kpis.expired > 0} />
      </div>

      {/* Barre d'outils */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        {/* Filtres */}
        <div style={{ display: 'flex', gap: 6 }}>
          {[
            { id: 'all',      label: 'Tous' },
            { id: 'active',   label: 'Actifs' },
            { id: 'expiring', label: '⚠️ Expirent bientôt' },
            { id: 'expired',  label: 'Expirés' },
            { id: 'suspended',label: 'Suspendus' },
          ].map(f => (
            <button key={f.id} onClick={() => setFilter(f.id)} style={{
              ...btnGhost, fontSize: 12,
              background: filter === f.id ? '#eff6ff' : 'transparent',
              color: filter === f.id ? '#1d4ed8' : '#6b7280',
              borderColor: filter === f.id ? '#93c5fd' : '#e5e7eb',
              fontWeight: filter === f.id ? 700 : 500,
            }}>{f.label}</button>
          ))}
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={handleReminders} disabled={reminderLoading} style={{ ...btnGhost, fontSize: 12 }}>
            {reminderLoading ? '...' : '📩 Envoyer rappels'}
          </button>
          <button onClick={handleBlockExpired} disabled={blockLoading} style={{ ...btnDanger, fontSize: 12, padding: '6px 14px' }}>
            {blockLoading ? '...' : '🔒 Bloquer expirés'}
          </button>
          <button onClick={() => setShowForm(v => !v)} style={btnSmall}>
            {showForm ? '✕ Annuler' : '+ Nouvel abonnement'}
          </button>
        </div>
      </div>

      {/* Formulaire de création */}
      {showForm && (
        <Card title="Créer un abonnement">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div>
              <label style={labelStyle}>ID Boutique *</label>
              <input
                style={inputStyle}
                type="number"
                placeholder="Ex: 42"
                value={formStoreId}
                onChange={e => setFormStoreId(e.target.value)}
              />
            </div>
            <div>
              <label style={labelStyle}>Plan</label>
              <select style={selectStyle} value={formPlan} onChange={e => setFormPlan(e.target.value)}>
                {PLAN_OPTIONS.map(p => (
                  <option key={p.value} value={p.value}>{p.label} — {p.monthly} DT/mois</option>
                ))}
              </select>
            </div>

            {/* Sélecteur durée avec prix dynamiques */}
            <div style={{ gridColumn: '1 / -1' }}>
              <label style={labelStyle}>Durée de l'abonnement</label>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                {DURATION_OPTIONS.map(d => {
                  const price = getPriceDT(formPlan, d.months);
                  const equiv = getMonthlyEquiv(formPlan, d.months);
                  const selected = formDuration === d.months;
                  return (
                    <button
                      key={d.months}
                      onClick={() => setFormDuration(d.months)}
                      style={{
                        border: `2px solid ${selected ? '#4f46e5' : '#e5e7eb'}`,
                        borderRadius: 12,
                        padding: '16px 12px',
                        background: selected ? '#eff6ff' : '#fff',
                        cursor: 'pointer',
                        textAlign: 'center',
                        transition: 'all .15s',
                      }}
                    >
                      <div style={{ fontSize: 16, fontWeight: 700, color: selected ? '#3730a3' : '#111827' }}>{d.label}</div>
                      <div style={{ fontSize: 22, fontWeight: 800, color: selected ? '#4f46e5' : '#374151', margin: '8px 0 4px' }}>
                        {price} DT
                      </div>
                      <div style={{ fontSize: 11, color: '#9ca3af' }}>{equiv} DT/mois</div>
                      {d.badge && (
                        <div style={{
                          marginTop: 8, padding: '2px 8px', borderRadius: 20, fontSize: 11, fontWeight: 700,
                          background: '#d1fae5', color: '#065f46', display: 'inline-block',
                        }}>
                          {d.badge}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            <div style={{ gridColumn: '1 / -1' }}>
              <label style={labelStyle}>Notes (optionnel)</label>
              <input
                style={inputStyle}
                placeholder="Raison, commentaire..."
                value={formNotes}
                onChange={e => setFormNotes(e.target.value)}
              />
            </div>
          </div>

          {/* Récapitulatif */}
          <div style={{ marginTop: 20, background: '#f9fafb', borderRadius: 10, padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <span style={{ fontSize: 13, color: '#6b7280' }}>Récap : </span>
              <strong style={{ fontSize: 14, color: '#111827' }}>
                {PLAN_META[formPlan]?.label} — {formDuration} mois
              </strong>
              <span style={{ fontSize: 13, color: '#6b7280' }}> → </span>
              <strong style={{ fontSize: 16, color: '#4f46e5' }}>{priceDT} DT</strong>
              <span style={{ fontSize: 12, color: '#9ca3af' }}> ({monthlyEquiv} DT/mois)</span>
            </div>
            <button onClick={handleCreate} disabled={formLoading} style={btnSuccess}>
              {formLoading ? 'Création...' : `✓ Créer — ${priceDT} DT`}
            </button>
          </div>
        </Card>
      )}

      {/* Tableau abonnements */}
      <Card noPad>
        {loading ? <Loader /> : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead style={{ background: '#f9fafb', borderBottom: '1px solid #f3f4f6' }}>
                <tr>
                  {['Boutique', 'Plan', 'Durée', 'Prix payé', 'Expire le', 'Jours rest.', 'Statut', 'Rappels', 'Créé par'].map(h => (
                    <th key={h} style={{ padding: '11px 16px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {subs.map((s, i) => {
                  const days = s.days_remaining;
                  const isUrgent = s.status === 'active' && days <= 7;
                  return (
                    <tr
                      key={s.id}
                      style={{ borderTop: i ? '1px solid #f9fafb' : 'none', background: isUrgent ? '#fffbeb' : '' }}
                      onMouseEnter={e => e.currentTarget.style.background = isUrgent ? '#fef3c7' : '#fafafa'}
                      onMouseLeave={e => e.currentTarget.style.background = isUrgent ? '#fffbeb' : ''}
                    >
                      <td style={{ padding: '13px 16px' }}>
                        <div style={{ fontWeight: 700, color: '#111827' }}>{s.store_name}</div>
                        <div style={{ fontSize: 11, color: '#9ca3af' }}>#{s.tenant_id}</div>
                        {s.admin_email && <div style={{ fontSize: 11, color: '#6b7280' }}>{s.admin_email}</div>}
                      </td>
                      <td style={{ padding: '13px 16px' }}><PlanBadge code={s.plan_code} /></td>
                      <td style={{ padding: '13px 16px', fontWeight: 700, color: '#374151' }}>{s.duration_months} mois</td>
                      <td style={{ padding: '13px 16px', fontWeight: 700, color: '#4f46e5' }}>{s.price_paid_dt} DT</td>
                      <td style={{ padding: '13px 16px', color: '#6b7280', whiteSpace: 'nowrap' }}>
                        {fmtDate(s.expires_at)}
                      </td>
                      <td style={{ padding: '13px 16px' }}>
                        {s.status === 'active' ? (
                          <span style={{
                            fontWeight: 700,
                            color: days <= 1 ? '#dc2626' : days <= 7 ? '#d97706' : '#111827',
                          }}>
                            {days <= 0 ? '⛔ Expiré' : `${days}j`}
                          </span>
                        ) : '—'}
                      </td>
                      <td style={{ padding: '13px 16px' }}>
                        <StatusBadge status={s.status} daysLeft={s.status === 'active' ? days : null} />
                        {s.blocked_at && (
                          <div style={{ fontSize: 11, color: '#dc2626', marginTop: 4 }}>
                            Bloqué le {fmtDate(s.blocked_at)}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: '13px 16px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <ReminderDot sent={s.reminder_7d_sent_at} />
                          <span style={{ fontSize: 11, color: '#9ca3af' }}>J-7</span>
                          <ReminderDot sent={s.reminder_1d_sent_at} />
                          <span style={{ fontSize: 11, color: '#9ca3af' }}>J-1</span>
                        </div>
                      </td>
                      <td style={{ padding: '13px 16px', color: '#9ca3af', fontSize: 12 }}>
                        {s.created_by || '—'}
                      </td>
                    </tr>
                  );
                })}
                {!subs.length && (
                  <tr><td colSpan={9} style={{ padding: 48, textAlign: 'center', color: '#9ca3af' }}>Aucun abonnement trouvé</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 3 — Crédits IA (identique à l'original, inchangé)
// ══════════════════════════════════════════════════════════════════════════════
function TabCredits({ api }) {
  const toast = useToast();
  const [blocked, setBlocked]           = useState([]);
  const [blockedLoading, setBL]         = useState(true);
  const [renewLoading, setRL]           = useState(false);
  const [renewResult, setRR]            = useState(null);
  const [dryRun, setDryRun]             = useState(false);
  const [bonusTenant, setBonusTenant]   = useState('');
  const [bonusCredits, setBonusCredits] = useState('');
  const [bonusReason, setBonusReason]   = useState('');
  const [bonusLoading, setBonusL]       = useState(false);
  const [ledgerTenant, setLedgerTenant] = useState('');
  const [ledger, setLedger]             = useState(null);
  const [ledgerLoading, setLL]          = useState(false);
  const [singleTenant, setSingleTenant] = useState('');
  const [singleLoading, setSL]          = useState(false);

  const fetchBlocked = useCallback(async () => {
    setBL(true);
    try {
      const res = await api.get('/admin/credits/blocked');
      setBlocked(res.data?.tenants || []);
    } catch { toast.error('Impossible de charger les tenants bloqués'); }
    finally   { setBL(false); }
  }, [api]);

  useEffect(() => { fetchBlocked(); }, [fetchBlocked]);

  const triggerRenewalAll = async () => {
    setRL(true); setRR(null);
    try {
      const res = await api.post('/admin/credits/trigger-renewal', { dry_run: dryRun });
      setRR(res.data);
      toast.success(dryRun ? `Simulation : ${res.data.summary?.renewed_count} tenants` : `✅ ${res.data.summary?.renewed_count} tenants renouvelés`);
      if (!dryRun) fetchBlocked();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Erreur renouvellement'); }
    finally     { setRL(false); }
  };

  const triggerRenewalOne = async () => {
    if (!singleTenant) return;
    setSL(true);
    try {
      const res = await api.post(`/admin/credits/trigger-renewal/${singleTenant}`, { dry_run: false });
      toast.success(`✅ Tenant #${singleTenant} — ${fmtNum(res.data.credits_allocated)} crédits`);
      fetchBlocked(); setSingleTenant('');
    } catch (e) { toast.error(e?.response?.data?.detail || 'Tenant introuvable'); }
    finally     { setSL(false); }
  };

  const grantBonus = async () => {
    if (!bonusTenant || !bonusCredits || !bonusReason) { toast.error('Remplissez tous les champs'); return; }
    setBonusL(true);
    try {
      await api.post('/admin/credits/grant-bonus', {
        tenant_id: parseInt(bonusTenant),
        credits: parseInt(bonusCredits),
        reason: bonusReason,
        created_by: 'admin:superadmin',
      });
      toast.success(`✅ +${fmtNum(parseInt(bonusCredits))} crédits → tenant #${bonusTenant}`);
      setBonusTenant(''); setBonusCredits(''); setBonusReason('');
      fetchBlocked();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Erreur octroi bonus'); }
    finally     { setBonusL(false); }
  };

  const fetchLedger = async () => {
    if (!ledgerTenant) return;
    setLL(true); setLedger(null);
    try {
      const res = await api.get(`/admin/credits/ledger/${ledgerTenant}?limit=30`);
      setLedger(res.data);
    } catch { toast.error('Tenant introuvable'); }
    finally   { setLL(false); }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <Card title="🚫 Tenants IA bloqués" action={<button onClick={fetchBlocked} style={btnGhost}>↺ Actualiser</button>} noPad>
        {blockedLoading ? <Loader /> : blocked.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '36px 0', color: '#10b981', fontWeight: 600 }}>✅ Aucun tenant bloqué actuellement</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead style={{ background: '#fef2f2' }}>
                <tr>{['Tenant', 'Plan', 'Crédits', 'Usage %', 'Action'].map(h => (
                  <th key={h} style={{ padding: '10px 16px', textAlign: 'left', fontSize: 11, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase' }}>{h}</th>
                ))}</tr>
              </thead>
              <tbody>
                {blocked.map((t, i) => (
                  <tr key={t.tenant_id} style={{ borderTop: i ? '1px solid #fef2f2' : 'none', background: '#fffafa' }}>
                    <td style={{ padding: '12px 16px', fontWeight: 700, color: '#dc2626' }}>#{t.tenant_id}</td>
                    <td style={{ padding: '12px 16px' }}><PlanBadge code={t.plan_code} /></td>
                    <td style={{ padding: '12px 16px', fontSize: 12, color: '#6b7280' }}>{fmtNum(t.ai_credits_used)} / {fmtNum(t.ai_credits_allocated)}</td>
                    <td style={{ padding: '12px 16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <ProgressBar pct={t.usage_pct} blocked />
                        <span style={{ fontSize: 12, fontWeight: 700, color: '#dc2626' }}>{t.usage_pct}%</span>
                      </div>
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      <button onClick={() => { setSingleTenant(String(t.tenant_id)); }} style={btnSmall}>
                        Renouveler
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        <Card title="🔄 Renouvellement global">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
              <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
              Mode simulation (dry run)
            </label>
            <button onClick={triggerRenewalAll} disabled={renewLoading} style={btnSmall}>
              {renewLoading ? 'En cours...' : dryRun ? '🔍 Simuler renouvellement' : '🔄 Lancer le renouvellement'}
            </button>
            {renewResult && (
              <div style={{ background: '#f9fafb', borderRadius: 8, padding: 12, fontSize: 12 }}>
                <strong>Résultat :</strong> {renewResult.summary?.renewed_count} tenants traités
              </div>
            )}
          </div>
        </Card>

        <Card title="⚡ Renouveler un tenant">
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              style={{ ...inputStyle, flex: 1 }}
              placeholder="ID tenant (ex: 42)"
              value={singleTenant}
              onChange={e => setSingleTenant(e.target.value)}
              type="number"
            />
            <button onClick={triggerRenewalOne} disabled={singleLoading} style={btnSmall}>
              {singleLoading ? '...' : 'Renouveler'}
            </button>
          </div>
        </Card>
      </div>

      <Card title="🎁 Octroyer des crédits bonus">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr auto', gap: 12, alignItems: 'end' }}>
          <div>
            <label style={labelStyle}>ID Tenant</label>
            <input style={inputStyle} placeholder="42" type="number" value={bonusTenant} onChange={e => setBonusTenant(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>Crédits</label>
            <input style={inputStyle} placeholder="500" type="number" value={bonusCredits} onChange={e => setBonusCredits(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>Raison</label>
            <input style={inputStyle} placeholder="Compensation, promo..." value={bonusReason} onChange={e => setBonusReason(e.target.value)} />
          </div>
          <button onClick={grantBonus} disabled={bonusLoading} style={btnSuccess}>
            {bonusLoading ? '...' : 'Octroyer'}
          </button>
        </div>
      </Card>

      <Card title="📋 Journal d'un tenant">
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <input style={{ ...inputStyle, maxWidth: 200 }} placeholder="ID tenant" type="number" value={ledgerTenant} onChange={e => setLedgerTenant(e.target.value)} />
          <button onClick={fetchLedger} disabled={ledgerLoading} style={btnSmall}>{ledgerLoading ? '...' : 'Charger'}</button>
        </div>
        {ledger && (
          <div style={{ overflowX: 'auto', maxHeight: 300, overflowY: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead style={{ position: 'sticky', top: 0, background: '#f9fafb' }}>
                <tr>{['Type', 'Delta', 'Solde', 'Description', 'Date'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 700, color: '#9ca3af', fontSize: 11, textTransform: 'uppercase' }}>{h}</th>
                ))}</tr>
              </thead>
              <tbody>
                {(ledger.entries || []).map((e, i) => (
                  <tr key={i} style={{ borderTop: '1px solid #f3f4f6' }}>
                    <td style={{ padding: '8px 12px' }}><span style={{ padding: '2px 8px', borderRadius: 10, background: '#eff6ff', color: '#1d4ed8', fontSize: 11 }}>{e.entry_type}</span></td>
                    <td style={{ padding: '8px 12px', fontWeight: 700, color: e.credits_delta > 0 ? '#10b981' : '#ef4444' }}>
                      {e.credits_delta > 0 ? '+' : ''}{fmtNum(e.credits_delta)}
                    </td>
                    <td style={{ padding: '8px 12px' }}>{fmtNum(e.credits_balance_after)}</td>
                    <td style={{ padding: '8px 12px', color: '#6b7280' }}>{e.description || '—'}</td>
                    <td style={{ padding: '8px 12px', color: '#9ca3af' }}>{fmtDate(e.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 4 — Statistiques (inchangé)
// ══════════════════════════════════════════════════════════════════════════════
const PLAN_LABELS = { starter: 'Starter', business: 'Business', premium: 'Premium', pro_whatsapp: 'Pro WA' };

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s, p) => s + (p.value || 0), 0);
  return (
    <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: '12px 16px', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}>
      <p style={{ fontWeight: 700, marginBottom: 8, color: '#111827' }}>{label}</p>
      {payload.map(p => p.value > 0 && (
        <p key={p.dataKey} style={{ color: p.fill, margin: '3px 0', fontSize: 13 }}>
          {PLAN_LABELS[p.dataKey] || p.dataKey}: <strong>{fmtNum(p.value)}</strong>
        </p>
      ))}
      <p style={{ borderTop: '1px solid #f3f4f6', marginTop: 8, paddingTop: 8, fontWeight: 700, color: '#111827', fontSize: 13 }}>
        Total: <strong>{fmtNum(total)}</strong>
      </p>
    </div>
  );
}

function TabStats({ api }) {
  const toast = useToast();
  const [data, setData]     = useState(null);
  const [months, setMonths] = useState(6);
  const [loading, setLoading] = useState(false);

  const fetchStats = useCallback(async (m = months) => {
    setLoading(true);
    try {
      const res = await api.get(`/admin/credits/stats?months=${m}`);
      setData(res.data);
    } catch { toast.error('Impossible de charger les statistiques'); }
    finally   { setLoading(false); }
  }, [api, months]);

  const handleMonthsChange = (m) => { setMonths(m); fetchStats(m); };
  useEffect(() => { fetchStats(); }, []);

  const currentMonth = data?.months?.[data.months.length - 1] || {};
  const grandTotal = data?.months?.reduce((s, m) => s + (m.total || 0), 0) || 0;
  const peakMonth = data?.months?.reduce((a, b) => (b.total || 0) > (a.total || 0) ? b : a, { total: 0 });
  const prevMonth = data?.months?.[data.months.length - 2];
  const trend = (prevMonth?.total && currentMonth?.total)
    ? Math.round(((currentMonth.total - prevMonth.total) / prevMonth.total) * 100)
    : null;
  const planTotals = PLAN_OPTIONS.map(p => ({
    name: p.label, value: data?.months?.reduce((s, m) => s + (m[p.value] || 0), 0) || 0, fill: p.color,
  })).filter(p => p.value > 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <p style={{ fontSize: 14, color: '#6b7280' }}>Consommation de crédits IA par plan sur la période sélectionnée.</p>
        <div style={{ display: 'flex', gap: 6 }}>
          {[3, 6, 12].map(m => (
            <button key={m} onClick={() => handleMonthsChange(m)} style={{
              ...btnGhost, fontWeight: months === m ? 700 : 500,
              background: months === m ? '#eff6ff' : 'transparent',
              color: months === m ? '#1d4ed8' : '#6b7280',
              borderColor: months === m ? '#93c5fd' : '#e5e7eb',
            }}>{m} mois</button>
          ))}
          <button onClick={() => fetchStats()} style={btnGhost}>↺</button>
        </div>
      </div>

      {loading ? <Loader /> : !data ? (
        <div style={{ textAlign: 'center', padding: 48, color: '#9ca3af' }}>Aucune donnée disponible</div>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
            <KpiCard label="Crédits consommés (total)" value={fmtNum(grandTotal)} sub={`sur ${months} mois`} color="#4f46e5" />
            <KpiCard label={`Ce mois — ${currentMonth.label || ''}`} value={fmtNum(currentMonth.total)}
              sub={trend !== null ? (trend >= 0 ? `↑ +${trend}% vs mois préc.` : `↓ ${trend}% vs mois préc.`) : ''}
              color={trend !== null ? (trend >= 0 ? '#10b981' : '#ef4444') : '#111827'} />
            <KpiCard label="Mois record" value={fmtNum(peakMonth?.total)} sub={peakMonth?.label || '—'} color="#f59e0b" />
            <KpiCard label="Moy. mensuelle" value={fmtNum(Math.round(grandTotal / (data.months.length || 1)))} sub="crédits / mois" color="#6b7280" />
          </div>

          <Card title={`📊 Consommation mensuelle par plan — ${months} derniers mois`}
            action={<div style={{ display: 'flex', gap: 12, fontSize: 12 }}>
              {PLAN_OPTIONS.map(p => (
                <span key={p.value} style={{ display: 'flex', alignItems: 'center', gap: 5, color: '#374151' }}>
                  <span style={{ width: 10, height: 10, borderRadius: 3, background: p.color, display: 'inline-block' }} />{p.label}
                </span>
              ))}
            </div>}>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={data.months} margin={{ top: 4, right: 16, bottom: 4, left: 16 }} barSize={36}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 12, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 12, fill: '#9ca3af' }} axisLine={false} tickLine={false}
                  tickFormatter={v => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v} />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: '#f9fafb' }} />
                <Bar dataKey="starter"      stackId="a" fill={PLAN_COLORS.starter}      radius={[0,0,0,0]} />
                <Bar dataKey="business"     stackId="a" fill={PLAN_COLORS.business}     radius={[0,0,0,0]} />
                <Bar dataKey="premium"      stackId="a" fill={PLAN_COLORS.premium}      radius={[0,0,0,0]} />
                <Bar dataKey="pro_whatsapp" stackId="a" fill={PLAN_COLORS.pro_whatsapp} radius={[4,4,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </>
      )}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Page principale
// ══════════════════════════════════════════════════════════════════════════════
const TABS = [
  { id: 'stores',        label: '🏪 Boutiques & Plans' },
  { id: 'subscriptions', label: '🗓️ Abonnements' },
  { id: 'credits',       label: '✦ Crédits IA' },
  { id: 'stats',         label: '📊 Statistiques' },
];

export default function SuperAdmin() {
  const [tab, setTab] = useState('stores');
  const { api }       = useStore();

  return (
    <div style={{ padding: '24px 0', maxWidth: 1280, margin: '0 auto' }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, color: '#111827', margin: 0 }}>
          Super Admin — AutoCommerce SaaS Maghreb
        </h1>
        <p style={{ color: '#6b7280', marginTop: 6, fontSize: 14 }}>
          Pilotez les abonnements (3/6/12 mois), les crédits IA et les statistiques de consommation.
        </p>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 28, background: '#f3f4f6', borderRadius: 12, padding: 4, width: 'fit-content' }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: '8px 22px', borderRadius: 9, border: 'none', cursor: 'pointer',
            fontWeight: tab === t.id ? 700 : 500, fontSize: 14,
            background: tab === t.id ? '#fff' : 'transparent',
            color: tab === t.id ? '#111827' : '#6b7280',
            boxShadow: tab === t.id ? '0 1px 4px rgba(0,0,0,0.08)' : 'none',
            transition: 'all .15s',
          }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'stores'        && <TabStores        api={api} />}
      {tab === 'subscriptions' && <TabSubscriptions api={api} />}
      {tab === 'credits'       && <TabCredits       api={api} />}
      {tab === 'stats'         && <TabStats         api={api} />}
    </div>
  );
}
