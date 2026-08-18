// Dashboard des liens de paiement multi-pays avec création, partage et suivi
import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useStore } from '../context/StoreContext';
import { useToast } from '../context/ToastContext';
import { useConfirm } from '../context/ConfirmContext';

// ─── Helpers ──────────────────────────────────────────────────────────────────
const STATUS_COLORS = {
  pending: 'bg-yellow-100 text-yellow-800 border-yellow-200',
  paid:    'bg-green-100 text-green-800 border-green-200',
  expired: 'bg-gray-100 text-gray-600 border-gray-200',
  failed:  'bg-red-100 text-red-800 border-red-200',
};

const STATUS_LABELS = {
  pending: '⏳ En attente',
  paid:    '✅ Payé',
  expired: '⌛ Expiré',
  failed:  '❌ Échoué',
};

const PROVIDER_LABELS = {
  stripe:  '💳 Stripe',
  flouci:  '🇹🇳 Flouci',
  clix:    '🇹🇳 Clix',
  tnpay:   '🇹🇳 TnPay',
  cmi:     '🇲🇦 CMI',
  aliapay: '🇩🇿 Alia Pay',
  nexus:   '🌍 Nexus Africa',
  cash:    '💵 Espèces',
};

const CHANNEL_ICONS = {
  whatsapp:  '💬',
  facebook:  '📘',
  instagram: '📸',
  manual:    '✏️',
  sms:       '📱',
  email:     '📧',
};

function formatAmount(amount, currency) {
  return new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency: currency || 'EUR',
    minimumFractionDigits: 2,
  }).format(amount);
}

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'à l\'instant';
  if (mins < 60) return `il y a ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `il y a ${hours}h`;
  const days = Math.floor(hours / 24);
  return `il y a ${days}j`;
}

// ─── Composant : Badge de statut ──────────────────────────────────────────────
function StatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${STATUS_COLORS[status] || 'bg-gray-100 text-gray-600'}`}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

// ─── Composant : Boutons de partage ──────────────────────────────────────────
function ShareButtons({ link, onSend }) {
  const toast = useToast();
  if (!link.url) return null;

  const encodedUrl = encodeURIComponent(link.url);
  const encodedText = encodeURIComponent(
    `💳 Votre lien de paiement : ${link.description || 'Paiement'}\n💰 Montant : ${formatAmount(link.amount, link.currency)}\n🔗 ${link.url}`
  );

  const shareLinks = [
    {
      label: 'WhatsApp',
      icon: '💬',
      color: 'bg-green-500 hover:bg-green-600',
      url: `https://wa.me/?text=${encodedText}`,
    },
    {
      label: 'Facebook',
      icon: '📘',
      color: 'bg-blue-600 hover:bg-blue-700',
      url: `https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`,
    },
    {
      label: 'Instagram',
      icon: '📸',
      color: 'bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600',
      url: null,
      action: () => {
        navigator.clipboard.writeText(link.url);
        toast.success('Lien copié ! Collez-le dans votre story ou message Instagram.');
      },
    },
    {
      label: 'Copier',
      icon: '📋',
      color: 'bg-gray-500 hover:bg-gray-600',
      url: null,
      action: () => {
        navigator.clipboard.writeText(link.url);
        toast.success('Lien copié dans le presse-papiers !');
      },
    },
  ];

  return (
    <div className="flex flex-wrap gap-2 mt-3">
      {shareLinks.map((s) => (
        <button
          key={s.label}
          onClick={() => {
            if (s.action) {
              s.action();
            } else if (s.url) {
              window.open(s.url, '_blank', 'noopener,noreferrer,width=600,height=400');
            }
          }}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-white text-xs font-medium transition-all ${s.color}`}
          title={`Partager sur ${s.label}`}
        >
          <span>{s.icon}</span>
          <span>{s.label}</span>
        </button>
      ))}
      <button
        onClick={() => onSend(link)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium transition-all"
        title="Envoyer via l'API"
      >
        <span>📤</span>
        <span>Envoyer</span>
      </button>
    </div>
  );
}

// ─── Composant : Modal de création ───────────────────────────────────────────
function CreateLinkModal({ onClose, onCreated, api }) {
  const [form, setForm] = useState({
    amount: '',
    currency: 'EUR',
    description: '',
    customer_name: '',
    customer_phone: '',
    customer_email: '',
    channel: 'manual',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const currencies = ['EUR', 'TND', 'MAD', 'DZD', 'AED', 'USD', 'GBP', 'XOF'];
  const channels = [
    { value: 'manual', label: '✏️ Manuel' },
    { value: 'whatsapp', label: '💬 WhatsApp' },
    { value: 'facebook', label: '📘 Facebook' },
    { value: 'instagram', label: '📸 Instagram' },
  ];

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const { data } = await api.post('/payment-links/', {
        ...form,
        amount: parseFloat(form.amount),
      });
      onCreated(data);
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-6 border-b border-gray-100">
          <div>
            <h2 className="text-xl font-bold text-gray-900">💳 Créer un lien de paiement</h2>
            <p className="text-sm text-gray-500 mt-0.5">Le provider sera sélectionné automatiquement selon votre pays</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm">
              ⚠️ {error}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Montant *</label>
              <input
                type="number"
                step="0.01"
                min="0.01"
                required
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="0.00"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Devise</label>
              <select
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              >
                {currencies.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description *</label>
            <input
              type="text"
              required
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              placeholder="Ex: Commande #123, Prestation de service..."
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Canal d'origine</label>
            <div className="flex flex-wrap gap-2">
              {channels.map((ch) => (
                <button
                  key={ch.value}
                  type="button"
                  onClick={() => setForm({ ...form, channel: ch.value })}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
                    form.channel === ch.value
                      ? 'bg-indigo-600 text-white border-indigo-600'
                      : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'
                  }`}
                >
                  {ch.label}
                </button>
              ))}
            </div>
          </div>

          <div className="border-t border-gray-100 pt-4">
            <p className="text-sm font-medium text-gray-700 mb-3">Informations client (optionnel)</p>
            <div className="space-y-3">
              <input
                type="text"
                value={form.customer_name}
                onChange={(e) => setForm({ ...form, customer_name: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="Nom du client"
              />
              <input
                type="tel"
                value={form.customer_phone}
                onChange={(e) => setForm({ ...form, customer_phone: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="Téléphone (ex: +21698765432)"
              />
              <input
                type="email"
                value={form.customer_email}
                onChange={(e) => setForm({ ...form, customer_email: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                placeholder="Email du client"
              />
            </div>
          </div>

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
            >
              Annuler
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 px-4 py-2.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
            >
              {loading ? 'Génération...' : '✨ Créer le lien'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Composant : Modal d'envoi ────────────────────────────────────────────────
function SendModal({ link, onClose, api }) {
  const [form, setForm] = useState({
    channel: link.channel || 'whatsapp',
    recipient: link.customer_phone || '',
    message: '',
  });
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');

  const channels = [
    { value: 'whatsapp', label: '💬 WhatsApp', placeholder: '+21698765432' },
    { value: 'facebook', label: '📘 Facebook', placeholder: 'ID Messenger' },
    { value: 'instagram', label: '📸 Instagram', placeholder: 'ID Instagram' },
    { value: 'email', label: '📧 Email', placeholder: 'client@email.com' },
  ];

  const handleSend = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await api.post(`/payment-links/${link.id}/send`, form);
      setSuccess(true);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between p-6 border-b border-gray-100">
          <h2 className="text-lg font-bold text-gray-900">📤 Envoyer le lien</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
        </div>

        {success ? (
          <div className="p-6 text-center">
            <div className="text-5xl mb-3">✅</div>
            <p className="text-lg font-semibold text-gray-900">Lien envoyé avec succès !</p>
            <p className="text-sm text-gray-500 mt-1">Le client a reçu le lien de paiement.</p>
            <button onClick={onClose} className="mt-4 px-6 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700">
              Fermer
            </button>
          </div>
        ) : (
          <form onSubmit={handleSend} className="p-6 space-y-4">
            {error && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-red-700 text-sm">
                ⚠️ {error}
              </div>
            )}

            <div className="bg-indigo-50 rounded-lg p-3 text-sm">
              <p className="font-medium text-indigo-900">{link.description}</p>
              <p className="text-indigo-700">{formatAmount(link.amount, link.currency)}</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Canal d'envoi</label>
              <div className="grid grid-cols-2 gap-2">
                {channels.map((ch) => (
                  <button
                    key={ch.value}
                    type="button"
                    onClick={() => setForm({ ...form, channel: ch.value })}
                    className={`px-3 py-2 rounded-lg text-sm font-medium border transition-all text-left ${
                      form.channel === ch.value
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'
                    }`}
                  >
                    {ch.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Destinataire *</label>
              <input
                type="text"
                required
                value={form.recipient}
                onChange={(e) => setForm({ ...form, recipient: e.target.value })}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500"
                placeholder={channels.find((c) => c.value === form.channel)?.placeholder || ''}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Message (optionnel)</label>
              <textarea
                value={form.message}
                onChange={(e) => setForm({ ...form, message: e.target.value })}
                rows={2}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-500 resize-none"
                placeholder="Message personnalisé (le lien sera ajouté automatiquement)"
              />
            </div>

            <div className="flex gap-3">
              <button type="button" onClick={onClose} className="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50">
                Annuler
              </button>
              <button
                type="submit"
                disabled={loading}
                className="flex-1 px-4 py-2.5 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {loading ? 'Envoi...' : '📤 Envoyer'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

// ─── Composant : Carte de lien ────────────────────────────────────────────────
function PaymentLinkCard({ link, onSend, onDelete }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`bg-white rounded-xl border transition-all ${
      link.status === 'paid' ? 'border-green-200 shadow-green-50' : 'border-gray-200'
    } shadow-sm hover:shadow-md`}>
      <div className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <StatusBadge status={link.status} />
              <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
                {PROVIDER_LABELS[link.provider] || link.provider}
              </span>
              {link.channel && (
                <span className="text-xs text-gray-500">
                  {CHANNEL_ICONS[link.channel] || '📲'} {link.channel}
                </span>
              )}
            </div>
            <p className="font-semibold text-gray-900 mt-1.5 truncate">{link.description || 'Paiement'}</p>
            <p className="text-2xl font-bold text-indigo-600 mt-0.5">
              {formatAmount(link.amount, link.currency)}
            </p>
          </div>
          <div className="text-right flex-shrink-0">
            <p className="text-xs text-gray-400">{timeAgo(link.created_at)}</p>
          </div>
        </div>

        {(link.customer_name || link.customer_phone) && (
          <div className="mt-2 flex items-center gap-3 text-xs text-gray-500">
            {link.customer_name && <span>👤 {link.customer_name}</span>}
            {link.customer_phone && <span>📱 {link.customer_phone}</span>}
          </div>
        )}

        <div className="mt-3 flex items-center gap-2 flex-wrap">
          {link.url && (
            <a
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            >
              🔗 Voir le lien
            </a>
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 ml-auto"
          >
            {expanded ? '▲ Moins' : '▼ Partager'}
          </button>
        </div>

        {expanded && (
          <ShareButtons link={link} onSend={onSend} />
        )}
      </div>

      <div className="px-4 py-2.5 bg-gray-50 rounded-b-xl border-t border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-3 text-xs text-gray-400">
          {link.sent_at && <span>📤 Envoyé {timeAgo(link.sent_at)}</span>}
          {link.paid_at && <span className="text-green-600">✅ Payé {timeAgo(link.paid_at)}</span>}
        </div>
        {link.status === 'pending' && (
          <button
            onClick={() => onDelete(link.id)}
            className="text-xs text-red-400 hover:text-red-600 transition-colors"
          >
            🗑️ Supprimer
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Composant : Statistiques ─────────────────────────────────────────────────
function AnalyticsBar({ analytics }) {
  if (!analytics) return null;
  const { by_status = {}, total_paid = 0, total_pending = 0 } = analytics;

  const stats = [
    { label: 'Total payé', value: `${total_paid.toLocaleString('fr-FR')} €`, icon: '💰', color: 'text-green-600' },
    { label: 'En attente', value: total_pending, icon: '⏳', color: 'text-yellow-600' },
    { label: 'Liens payés', value: by_status.paid?.count || 0, icon: '✅', color: 'text-green-600' },
    { label: 'Liens créés', value: Object.values(by_status).reduce((s, v) => s + (v.count || 0), 0), icon: '🔗', color: 'text-indigo-600' },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {stats.map((s) => (
        <div key={s.label} className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-2xl">{s.icon}</span>
            <span className={`text-lg font-bold ${s.color}`}>{s.value}</span>
          </div>
          <p className="text-xs text-gray-500 mt-1">{s.label}</p>
        </div>
      ))}
    </div>
  );
}

// ─── PAGE PRINCIPALE ──────────────────────────────────────────────────────────
export default function PaymentLinks() {
  const { api } = useStore();
  const { t } = useTranslation();
  const toast = useToast();
  const confirm = useConfirm();

  const [links, setLinks] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [sendTarget, setSendTarget] = useState(null);
  const [filterStatus, setFilterStatus] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  const fetchLinks = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [linksRes, analyticsRes] = await Promise.all([
        api.get('/payment-links/', { params: { page, limit: 12, status: filterStatus || undefined } }),
        api.get('/payment-links/analytics')
      ]);

      setLinks(linksRes.data.items || []);
      setTotalPages(linksRes.data.pages || 1);
      setAnalytics(analyticsRes.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  }, [api, page, filterStatus]);

  useEffect(() => {
    fetchLinks();
    const interval = setInterval(fetchLinks, 30000);
    return () => clearInterval(interval);
  }, [fetchLinks]);

  const handleDelete = async (id) => {
    if (!(await confirm('Supprimer ce lien de paiement ?'))) return;
    try {
      await api.delete(`/payment-links/${id}`);
      setLinks((prev) => prev.filter((l) => l.id !== id));
      toast.success('Lien supprimé');
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Erreur lors de la suppression');
    }
  };

  const statusFilters = [
    { value: '', label: 'Tous' },
    { value: 'pending', label: '⏳ En attente' },
    { value: 'paid', label: '✅ Payés' },
    { value: 'expired', label: '⌛ Expirés' },
    { value: 'failed', label: '❌ Échoués' },
  ];

  return (
    <div className="p-4 lg:p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">💳 Liens de Paiement</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Générez et envoyez des liens de paiement sécurisés à vos clients
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2.5 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700 transition-colors shadow-sm"
        >
          <span className="text-lg">+</span>
          <span className="hidden sm:inline">Nouveau lien</span>
        </button>
      </div>

      <AnalyticsBar analytics={analytics} />

      <div className="flex items-center gap-2 mb-4 flex-wrap">
        {statusFilters.map((f) => (
          <button
            key={f.value}
            onClick={() => { setFilterStatus(f.value); setPage(1); }}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
              filterStatus === f.value
                ? 'bg-indigo-600 text-white border-indigo-600'
                : 'bg-white text-gray-600 border-gray-300 hover:border-indigo-400'
            }`}
          >
            {f.label}
          </button>
        ))}
        <button
          onClick={fetchLinks}
          className="ml-auto px-3 py-1.5 rounded-lg text-sm text-gray-500 hover:text-gray-700 border border-gray-200 hover:border-gray-300 transition-all"
          title="Rafraîchir"
        >
          🔄
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 mb-4 text-red-700 text-sm">
          ⚠️ {error}
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-gray-200 p-4 animate-pulse">
              <div className="h-4 bg-gray-200 rounded w-1/3 mb-3" />
              <div className="h-6 bg-gray-200 rounded w-2/3 mb-2" />
              <div className="h-8 bg-gray-200 rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : links.length === 0 ? (
        <div className="text-center py-16 bg-white rounded-xl border border-gray-200">
          <div className="text-5xl mb-4">💳</div>
          <h3 className="text-lg font-semibold text-gray-700">Aucun lien de paiement</h3>
          <p className="text-sm text-gray-500 mt-1 mb-4">
            Créez votre premier lien de paiement et envoyez-le à vos clients
          </p>
          <button
            onClick={() => setShowCreate(true)}
            className="px-6 py-2.5 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700 transition-colors"
          >
            ✨ Créer un lien
          </button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {links.map((link) => (
              <PaymentLinkCard
                key={link.id}
                link={link}
                onSend={(l) => setSendTarget(l)}
                onDelete={handleDelete}
              />
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-6">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm disabled:opacity-40 hover:bg-gray-50"
              >
                ← Précédent
              </button>
              <span className="text-sm text-gray-600">
                Page {page} / {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm disabled:opacity-40 hover:bg-gray-50"
              >
                Suivant →
              </button>
            </div>
          )}
        </>
      )}

      {showCreate && (
        <CreateLinkModal
          onClose={() => setShowCreate(false)}
          onCreated={(newLink) => {
            setLinks([newLink, ...links]);
            fetchLinks();
          }}
          api={api}
        />
      )}

      {sendTarget && (
        <SendModal
          link={sendTarget}
          onClose={() => setSendTarget(null)}
          api={api}
        />
      )}
    </div>
  );
}
