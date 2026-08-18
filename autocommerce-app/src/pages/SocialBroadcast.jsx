// src/pages/SocialBroadcast.jsx
// Publication automatique IA (GPT-4o + DALL-E 3) sur les réseaux sociaux
// Design Tailwind mobile-first — cohérent avec le dashboard AutoCommerce V10

import React, { useState, useEffect, useCallback } from 'react';
import axiosApi, { extractErrorMessage } from '../api';

/* ─── API helper (compat — utilise désormais l'instance Axios centralisée) ──
   Conserve la signature historique : api(path, { method, body, headers })
   afin de ne casser aucun call-site existant.                              */
const api = async (path, opts = {}) => {
  const method = (opts.method || 'GET').toUpperCase();
  let data = opts.body;
  if (typeof data === 'string') {
    try { data = JSON.parse(data); } catch { /* keep as string */ }
  }
  try {
    const res = await axiosApi.request({
      url: path,
      method,
      data: ['GET', 'HEAD'].includes(method) ? undefined : data,
      headers: opts.headers || undefined,
    });
    if (res.status === 204) return null;
    return res.data;
  } catch (err) {
    throw new Error(extractErrorMessage(err));
  }
};

/* ─── Constants ──────────────────────────────────────────────────────────── */
const NETWORKS = [
  { id: 'instagram', label: 'Instagram', icon: '📸' },
  { id: 'facebook',  label: 'Facebook',  icon: '👤' },
  { id: 'tiktok',    label: 'TikTok',    icon: '🎵' },
];

const STATUS_STYLES = {
  published: { label: 'Publié',   cls: 'bg-green-100 text-green-700 border-green-200' },
  scheduled: { label: 'Planifié', cls: 'bg-blue-100 text-blue-700 border-blue-200' },
  failed:    { label: 'Échoué',   cls: 'bg-red-100 text-red-700 border-red-200' },
  pending:   { label: 'En cours', cls: 'bg-amber-100 text-amber-700 border-amber-200' },
  cancelled: { label: 'Annulé',   cls: 'bg-gray-100 text-gray-600 border-gray-200' },
};

const VOICES  = ['professionnel', 'décontracté', 'urgent', 'festif', 'inspirant'];
const LANGS   = [['fr', 'Français'], ['ar', 'Arabe'], ['darija', 'Darija']];
const EMOJIS  = [['none', 'Aucun'], ['minimal', 'Minimal'], ['moderate', 'Modéré'], ['expressive', 'Expressif']];
const DAYS_FR = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];

/* ─── Toast ──────────────────────────────────────────────────────────────── */
function Toast({ msg, type, onClose }) {
  useEffect(() => {
    if (msg) { const t = setTimeout(onClose, 4500); return () => clearTimeout(t); }
  }, [msg, onClose]);
  if (!msg) return null;
  return (
    <div className={`fixed bottom-5 right-5 z-50 flex items-center gap-3 px-5 py-3.5 rounded-2xl shadow-xl text-sm font-semibold max-w-sm border ${
      type === 'error'
        ? 'bg-red-50 border-red-200 text-red-700'
        : 'bg-green-50 border-green-200 text-green-700'
    }`}>
      <span className="text-lg">{type === 'error' ? '❌' : '✅'}</span>
      <span className="flex-1">{msg}</span>
      <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none ml-2">×</button>
    </div>
  );
}

/* ─── Network Badge ──────────────────────────────────────────────────────── */
function NetworkBadge({ network, connected }) {
  const n = NETWORKS.find(x => x.id === network);
  if (!n) return null;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${
      connected
        ? 'bg-green-50 border-green-200 text-green-700'
        : 'bg-gray-50 border-gray-200 text-gray-500'
    }`}>
      {n.icon} {n.label} {connected ? '✓' : '–'}
    </span>
  );
}

/* ─── Network Toggle ─────────────────────────────────────────────────────── */
function NetworkToggle({ value, onChange }) {
  return (
    <div className="flex flex-wrap gap-2">
      {NETWORKS.map(n => {
        const active = value.includes(n.id);
        return (
          <button
            key={n.id}
            type="button"
            onClick={() => onChange(active ? value.filter(x => x !== n.id) : [...value, n.id])}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold border-2 transition-all ${
              active
                ? 'bg-violet-600 border-violet-600 text-white shadow-sm'
                : 'bg-white border-gray-200 text-gray-600 hover:border-violet-300'
            }`}
          >
            {n.icon} {n.label}
          </button>
        );
      })}
    </div>
  );
}

/* ─── Status Badge ───────────────────────────────────────────────────────── */
function StatusBadge({ status }) {
  const s = STATUS_STYLES[status] || STATUS_STYLES.pending;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${s.cls}`}>
      {s.label}
    </span>
  );
}

/* ─── Toggle Switch ──────────────────────────────────────────────────────── */
function ToggleSwitch({ checked, onChange }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
        checked ? 'bg-violet-600' : 'bg-gray-200'
      }`}
    >
      <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
        checked ? 'translate-x-6' : 'translate-x-1'
      }`} />
    </button>
  );
}

/* ─── Card wrapper ───────────────────────────────────────────────────────── */
function Card({ children, className = '' }) {
  return (
    <div className={`premium-card p-5 ${className}`}>
      {children}
    </div>
  );
}

/* ─── Label ──────────────────────────────────────────────────────────────── */
function Label({ children }) {
  return (
    <label className="block text-xs font-semibold text-gray-500 mb-1.5 uppercase tracking-wide">
      {children}
    </label>
  );
}

/* ─── Input ──────────────────────────────────────────────────────────────── */
function Input({ className = '', ...props }) {
  return (
    <input
      className={`w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent transition ${className}`}
      {...props}
    />
  );
}

/* ─── Select ─────────────────────────────────────────────────────────────── */
function Select({ className = '', children, ...props }) {
  return (
    <select
      className={`w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm text-gray-900 bg-white focus:outline-none focus:ring-2 focus:ring-violet-400 ${className}`}
      {...props}
    >
      {children}
    </select>
  );
}

/* ─── Textarea ───────────────────────────────────────────────────────────── */
function Textarea({ className = '', ...props }) {
  return (
    <textarea
      className={`w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none ${className}`}
      {...props}
    />
  );
}

/* ─── Primary Button ─────────────────────────────────────────────────────── */
function BtnPrimary({ children, className = '', ...props }) {
  return (
    <button
      className={`flex items-center justify-center gap-2 bg-gradient-to-r from-violet-600 to-pink-500 text-white font-bold rounded-xl px-4 py-3 text-sm hover:opacity-90 transition shadow-md disabled:opacity-40 disabled:cursor-not-allowed ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

/* ─── Secondary Button ───────────────────────────────────────────────────── */
function BtnSecondary({ children, className = '', ...props }) {
  return (
    <button
      className={`flex items-center justify-center gap-2 bg-white border-2 border-violet-300 text-violet-700 font-semibold rounded-xl px-4 py-3 text-sm hover:bg-violet-50 transition disabled:opacity-40 disabled:cursor-not-allowed ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

/* ─── TAB: Publier maintenant ────────────────────────────────────────────── */
function PublishTab({ socialStatus, onToast }) {
  const [topic, setTopic]             = useState('');
  const [networks, setNetworks]       = useState(['instagram', 'facebook']);
  const [postType, setPostType]       = useState('post');
  const [genImage, setGenImage]       = useState(true);
  const [customCaption, setCustomCaption] = useState('');
  const [customImage, setCustomImage] = useState('');
  const [extraContext, setExtraContext] = useState('');
  const [loading, setLoading]         = useState(false);
  const [preview, setPreview]         = useState(null);

  const connectedNets = NETWORKS.filter(n => socialStatus[n.id]?.connected);

  const handleGenerate = async () => {
    if (!topic.trim()) return;
    setLoading(true);
    setPreview(null);
    try {
      const data = await api('social/broadcast/generate', {
        method: 'POST',
        body: JSON.stringify({
          topic,
          networks,
          post_type: postType,
          generate_image: genImage,
          custom_caption: customCaption || null,
          custom_image_url: customImage || null,
          extra_context: extraContext || null,
        }),
      });
      setPreview(data);
    } catch (e) {
      onToast(e.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handlePublish = async () => {
    setLoading(true);
    try {
      const data = await api('social/broadcast/publish', {
        method: 'POST',
        body: JSON.stringify({
          topic: topic || 'publication',
          networks,
          post_type: postType,
          generate_image: genImage,
          custom_caption: preview?.caption || customCaption || null,
          custom_image_url: preview?.image_url || customImage || null,
          extra_context: extraContext || null,
          publish_now: true,
        }),
      });
      onToast(`✅ Publié sur ${data.published} réseau(x) !`);
      setPreview(null);
      setTopic('');
      setCustomCaption('');
      setCustomImage('');
    } catch (e) {
      onToast(e.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
      {/* ── Formulaire ── */}
      <div className="space-y-4">
        {connectedNets.length === 0 && (
          <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-700">
            <span className="text-lg mt-0.5">⚠️</span>
            <span>
              Aucun réseau connecté.{' '}
              <a href="/settings" className="font-semibold underline hover:no-underline">
                Configurer dans Paramètres →
              </a>
            </span>
          </div>
        )}

        <Card className="space-y-4">
          <h3 className="font-semibold text-gray-900 text-sm">✍️ Contenu de la publication</h3>

          <div>
            <Label>Sujet / Annonce *</Label>
            <Input
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="Ex: Promo été -20%, Nouveau produit T-shirt, Ouverture exceptionnelle..."
            />
          </div>

          <div>
            <Label>Réseaux cibles</Label>
            <NetworkToggle value={networks} onChange={setNetworks} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Type de post</Label>
              <Select value={postType} onChange={e => setPostType(e.target.value)}>
                <option value="post">📷 Post</option>
                <option value="story">⭕ Story</option>
              </Select>
            </div>
            <div>
              <Label>Contexte</Label>
              <Input
                value={extraContext}
                onChange={e => setExtraContext(e.target.value)}
                placeholder="Prix, détails, offre..."
              />
            </div>
          </div>
        </Card>

        <Card className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-gray-900 text-sm">🎨 Image DALL-E 3</h3>
            <ToggleSwitch checked={genImage} onChange={setGenImage} />
          </div>
          {!genImage ? (
            <div>
              <Label>URL d'image personnalisée</Label>
              <Input
                value={customImage}
                onChange={e => setCustomImage(e.target.value)}
                placeholder="https://..."
              />
            </div>
          ) : (
            <p className="text-xs text-gray-400">
              DALL-E 3 générera automatiquement un visuel adapté à votre annonce selon le style configuré.
            </p>
          )}
        </Card>

        <Card className="space-y-3">
          <h3 className="font-semibold text-gray-900 text-sm">📝 Légende personnalisée</h3>
          <Textarea
            rows={3}
            value={customCaption}
            onChange={e => setCustomCaption(e.target.value)}
            placeholder="Laisser vide pour génération automatique par GPT-4o..."
          />
        </Card>

        <div className="flex flex-col sm:flex-row gap-3">
          <BtnSecondary
            className="flex-1"
            onClick={handleGenerate}
            disabled={loading || !topic.trim() || networks.length === 0}
          >
            {loading ? <><span className="animate-spin inline-block">⏳</span> Génération...</> : <><span>✨</span> Aperçu IA</>}
          </BtnSecondary>
          <BtnPrimary
            className="flex-1"
            onClick={handlePublish}
            disabled={loading || !topic.trim() || networks.length === 0}
          >
            {loading ? <><span className="animate-spin inline-block">⏳</span> Publication...</> : <><span>🚀</span> Publier maintenant</>}
          </BtnPrimary>
        </div>
      </div>

      {/* ── Aperçu ── */}
      <div className="space-y-4">
        {preview ? (
          <Card className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-gray-900 text-sm">👁️ Aperçu du post</h3>
              <span className="text-xs bg-violet-100 text-violet-700 px-2.5 py-1 rounded-full font-semibold">
                Généré par GPT-4o
              </span>
            </div>

            {preview.image_url && (
              <div className="rounded-xl overflow-hidden border border-gray-100">
                <img
                  src={preview.image_url}
                  alt="Visuel DALL-E 3"
                  className="w-full object-cover max-h-64"
                  onError={e => { e.target.style.display = 'none'; }}
                />
                {preview.image_prompt && (
                  <p className="px-3 py-2 text-xs text-gray-400 italic truncate bg-gray-50">
                    🎨 {preview.image_prompt}
                  </p>
                )}
              </div>
            )}

            {preview.dalle_error && (
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-700">
                ⚠️ Image non disponible : {preview.dalle_error}
              </div>
            )}

            <div className="bg-gray-50 rounded-xl p-4">
              <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">
                {preview.caption}
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              {networks.map(n => (
                <NetworkBadge key={n} network={n} connected={socialStatus[n]?.connected} />
              ))}
            </div>

            <BtnPrimary className="w-full" onClick={handlePublish} disabled={loading}>
              {loading ? <><span className="animate-spin inline-block">⏳</span> Publication...</> : <><span>🚀</span> Confirmer et publier</>}
            </BtnPrimary>
          </Card>
        ) : (
          <div className="bg-white rounded-2xl border border-dashed border-gray-200 p-10 flex flex-col items-center justify-center text-center gap-3 min-h-[280px]">
            <span className="text-5xl">🤖</span>
            <p className="font-semibold text-gray-700 text-sm">L'aperçu IA apparaîtra ici</p>
            <p className="text-xs text-gray-400 max-w-xs leading-relaxed">
              Saisissez un sujet, sélectionnez vos réseaux et cliquez sur "Aperçu IA" pour voir le contenu généré par GPT-4o et DALL-E 3.
            </p>
          </div>
        )}

        <div className="bg-gradient-to-br from-violet-50 to-pink-50 rounded-2xl border border-violet-100 p-4 space-y-2">
          <p className="text-xs font-bold text-violet-700 uppercase tracking-wide">🎨 Moteur IA</p>
          <div className="grid grid-cols-2 gap-2 text-xs text-gray-600">
            <div className="flex items-center gap-1.5">✍️ GPT-4o — Légendes</div>
            <div className="flex items-center gap-1.5">🖼️ DALL-E 3 — Visuels</div>
            <div className="flex items-center gap-1.5">📸 Instagram Graph API</div>
            <div className="flex items-center gap-1.5">👤 Facebook Pages API</div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── TAB: Planifier ─────────────────────────────────────────────────────── */
function ScheduleTab({ onToast }) {
  const [topic, setTopic]             = useState('');
  const [networks, setNetworks]       = useState(['instagram', 'facebook']);
  const [postType, setPostType]       = useState('post');
  const [genImage, setGenImage]       = useState(true);
  const [customCaption, setCustomCaption] = useState('');
  const [scheduledAt, setScheduledAt] = useState('');
  const [loading, setLoading]         = useState(false);
  const [scheduled, setScheduled]     = useState([]);
  const [loadingList, setLoadingList] = useState(true);

  const loadScheduled = useCallback(async () => {
    setLoadingList(true);
    try {
      setScheduled(await api('social/broadcast/scheduled') || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => { loadScheduled(); }, [loadScheduled]);

  const handleSchedule = async () => {
    if (!topic.trim() || !scheduledAt || networks.length === 0) return;
    setLoading(true);
    try {
      await api('social/broadcast/schedule', {
        method: 'POST',
        body: JSON.stringify({
          topic,
          networks,
          post_type: postType,
          generate_image: genImage,
          custom_caption: customCaption || null,
          scheduled_at: new Date(scheduledAt).toISOString(),
        }),
      });
      onToast('✅ Publication planifiée avec succès !');
      setTopic('');
      setCustomCaption('');
      setScheduledAt('');
      loadScheduled();
    } catch (e) {
      onToast(e.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async (id) => {
    try {
      await api(`social/broadcast/scheduled/${id}`, { method: 'DELETE' });
      onToast('Publication annulée.');
      loadScheduled();
    } catch (e) {
      onToast(e.message, 'error');
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
      <Card className="space-y-4">
        <h3 className="font-semibold text-gray-900 text-sm">⏰ Planifier une publication</h3>

        <div>
          <Label>Sujet *</Label>
          <Input
            value={topic}
            onChange={e => setTopic(e.target.value)}
            placeholder="Sujet de votre publication..."
          />
        </div>

        <div>
          <Label>Réseaux</Label>
          <NetworkToggle value={networks} onChange={setNetworks} />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Type</Label>
            <Select value={postType} onChange={e => setPostType(e.target.value)}>
              <option value="post">📷 Post</option>
              <option value="story">⭕ Story</option>
            </Select>
          </div>
          <div>
            <Label>Date et heure *</Label>
            <Input
              type="datetime-local"
              value={scheduledAt}
              onChange={e => setScheduledAt(e.target.value)}
              min={new Date(Date.now() + 5 * 60000).toISOString().slice(0, 16)}
            />
          </div>
        </div>

        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={genImage}
            onChange={e => setGenImage(e.target.checked)}
            className="w-4 h-4 accent-violet-600 rounded"
          />
          <span className="text-sm text-gray-700">🎨 Générer image DALL-E 3 maintenant</span>
        </label>

        <div>
          <Label>Légende (optionnel)</Label>
          <Textarea
            rows={3}
            value={customCaption}
            onChange={e => setCustomCaption(e.target.value)}
            placeholder="Laisser vide pour génération auto..."
          />
        </div>

        <BtnPrimary
          className="w-full"
          onClick={handleSchedule}
          disabled={loading || !topic.trim() || !scheduledAt || networks.length === 0}
        >
          {loading ? <><span className="animate-spin inline-block">⏳</span> Planification...</> : <><span>⏰</span> Planifier</>}
        </BtnPrimary>
      </Card>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-gray-900 text-sm">
            📅 Publications planifiées ({scheduled.length})
          </h3>
          <button
            onClick={loadScheduled}
            className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded-lg px-2.5 py-1.5 hover:bg-gray-50 transition"
          >
            ↺ Actualiser
          </button>
        </div>

        {loadingList ? (
          <div className="premium-card p-8 flex items-center justify-center">
            <span className="animate-spin text-2xl">⏳</span>
          </div>
        ) : scheduled.length === 0 ? (
          <div className="bg-white rounded-2xl border border-dashed border-gray-200 p-8 text-center">
            <p className="text-3xl mb-2">📅</p>
            <p className="text-sm text-gray-500">Aucune publication planifiée</p>
          </div>
        ) : (
          scheduled.map(p => (
            <Card key={p.id}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold text-blue-600 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-full">
                      ⏰ {new Date(p.scheduled_at).toLocaleString('fr-TN')}
                    </span>
                    <NetworkBadge network={p.network} connected />
                  </div>
                  {p.image_url && (
                    <img
                      src={p.image_url}
                      alt=""
                      className="w-12 h-12 object-cover rounded-lg"
                      onError={e => { e.target.style.display = 'none'; }}
                    />
                  )}
                  <p className="text-xs text-gray-600 line-clamp-2 leading-relaxed">{p.caption}</p>
                </div>
                <button
                  onClick={() => handleCancel(p.id)}
                  className="flex-shrink-0 text-xs text-red-500 border border-red-200 rounded-lg px-2.5 py-1.5 hover:bg-red-50 transition"
                >
                  Annuler
                </button>
              </div>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}

/* ─── TAB: Historique ────────────────────────────────────────────────────── */
function HistoryTab({ onToast }) {
  const [posts, setPosts]               = useState([]);
  const [filterStatus, setFilterStatus] = useState('');
  const [filterNetwork, setFilterNetwork] = useState('');
  const [loading, setLoading]           = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: 100 });
      if (filterStatus)  params.set('status', filterStatus);
      if (filterNetwork) params.set('network', filterNetwork);
      setPosts(await api(`social/broadcast/posts?${params}`) || []);
    } catch (e) {
      onToast(e.message, 'error');
    } finally {
      setLoading(false);
    }
  }, [filterStatus, filterNetwork]);

  useEffect(() => { load(); }, [load]);

  const handleDelete = async (id) => {
    try {
      await api(`social/broadcast/posts/${id}`, { method: 'DELETE' });
      onToast('Post supprimé.');
      load();
    } catch (e) {
      onToast(e.message, 'error');
    }
  };

  const stats = {
    published: posts.filter(p => p.status === 'published').length,
    scheduled: posts.filter(p => p.status === 'scheduled').length,
    failed:    posts.filter(p => p.status === 'failed').length,
  };

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Publiés',   value: stats.published, cls: 'text-green-600 bg-green-50 border-green-100' },
          { label: 'Planifiés', value: stats.scheduled, cls: 'text-blue-600 bg-blue-50 border-blue-100' },
          { label: 'Échoués',   value: stats.failed,    cls: 'text-red-600 bg-red-50 border-red-100' },
        ].map(s => (
          <div key={s.label} className={`rounded-2xl border p-4 text-center ${s.cls}`}>
            <p className="text-2xl font-bold">{s.value}</p>
            <p className="text-xs font-semibold mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-3 items-center">
        <Select
          className="w-auto"
          value={filterStatus}
          onChange={e => setFilterStatus(e.target.value)}
        >
          <option value="">Tous les statuts</option>
          {Object.entries(STATUS_STYLES).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </Select>
        <Select
          className="w-auto"
          value={filterNetwork}
          onChange={e => setFilterNetwork(e.target.value)}
        >
          <option value="">Tous les réseaux</option>
          {NETWORKS.map(n => <option key={n.id} value={n.id}>{n.icon} {n.label}</option>)}
        </Select>
        <button
          onClick={load}
          className="text-sm text-gray-500 hover:text-gray-700 border border-gray-200 rounded-xl px-3 py-2 hover:bg-gray-50 transition"
        >
          ↺ Actualiser
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16">
          <span className="animate-spin text-3xl">⏳</span>
        </div>
      ) : posts.length === 0 ? (
        <div className="bg-white rounded-2xl border border-dashed border-gray-200 p-12 text-center">
          <p className="text-4xl mb-3">📋</p>
          <p className="font-semibold text-gray-700">Aucune publication</p>
          <p className="text-sm text-gray-400 mt-1">Publiez votre premier post pour le voir ici.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {posts.map(p => (
            <Card key={p.id}>
              <div className="flex items-start gap-3">
                {p.image_url ? (
                  <img
                    src={p.image_url}
                    alt=""
                    className="w-14 h-14 object-cover rounded-xl flex-shrink-0"
                    onError={e => { e.target.style.display = 'none'; }}
                  />
                ) : (
                  <div className="w-14 h-14 rounded-xl bg-gray-100 flex items-center justify-center text-2xl flex-shrink-0">
                    {NETWORKS.find(n => n.id === p.network)?.icon || '📱'}
                  </div>
                )}
                <div className="flex-1 min-w-0 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={p.status} />
                    <NetworkBadge network={p.network} connected />
                    {p.published_at && (
                      <span className="text-xs text-gray-400">
                        {new Date(p.published_at).toLocaleString('fr-TN')}
                      </span>
                    )}
                    {p.source === 'ai_auto' && (
                      <span className="text-xs bg-violet-100 text-violet-700 px-2 py-0.5 rounded-full font-semibold">
                        🤖 IA Auto
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-700 line-clamp-2 leading-relaxed">{p.caption}</p>
                  {p.error && (
                    <p className="text-xs text-red-500 bg-red-50 rounded-lg px-2 py-1">⚠️ {p.error}</p>
                  )}
                </div>
                <button
                  onClick={() => handleDelete(p.id)}
                  className="flex-shrink-0 text-xs text-gray-400 hover:text-red-500 border border-gray-200 hover:border-red-200 rounded-lg px-2 py-1.5 transition"
                >
                  🗑️
                </button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─── TAB: Préférences ───────────────────────────────────────────────────── */
function PrefsTab({ onToast }) {
  const defaultConfig = {
    brand_name: '',
    brand_voice: 'professionnel',
    default_language: 'fr',
    hashtags: [],
    emoji_style: 'moderate',
    image_style: 'commercial product photo, clean background, professional lighting',
    image_colors: '',
    watermark_text: '',
    networks_enabled: ['instagram', 'facebook'],
    auto_schedule: false,
    post_times: ['09:00', '12:00', '18:00'],
    post_days: [0, 1, 2, 3, 4, 5, 6],
    max_posts_per_day: 3,
    timezone: 'Africa/Tunis',
  };

  const [config, setConfig]   = useState(defaultConfig);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving]   = useState(false);
  const [newHashtag, setNewHashtag] = useState('');

  const parseJsonField = (val, fallback) => {
    if (Array.isArray(val)) return val;
    try { return JSON.parse(val || JSON.stringify(fallback)); }
    catch { return fallback; }
  };

  useEffect(() => {
    api('social/broadcast/config')
      .then(data => {
        if (data) {
          setConfig(prev => ({
            ...prev,
            ...data,
            hashtags:         parseJsonField(data.hashtags, []),
            post_times:       parseJsonField(data.post_times, ['09:00', '12:00', '18:00']),
            post_days:        parseJsonField(data.post_days, [0, 1, 2, 3, 4, 5, 6]),
            networks_enabled: parseJsonField(data.networks_enabled, ['instagram', 'facebook']),
          }));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api('social/broadcast/config', {
        method: 'PUT',
        body: JSON.stringify(config),
      });
      onToast('✅ Préférences sauvegardées !');
    } catch (e) {
      onToast(e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const addHashtag = () => {
    const tag = newHashtag.trim().replace(/^#/, '');
    if (tag && !(config.hashtags || []).includes(tag)) {
      setConfig(c => ({ ...c, hashtags: [...(c.hashtags || []), tag] }));
      setNewHashtag('');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <span className="animate-spin text-3xl">⏳</span>
      </div>
    );
  }

  return (
    <div className="max-w-2xl space-y-5">
      {/* Identité de marque */}
      <Card className="space-y-4">
        <h3 className="font-semibold text-gray-900 text-sm">🏷️ Identité de marque</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <Label>Nom de marque</Label>
            <Input
              value={config.brand_name}
              onChange={e => setConfig(c => ({ ...c, brand_name: e.target.value }))}
              placeholder="Ex: Ma Boutique Tunisie"
            />
          </div>
          <div>
            <Label>Voix de marque</Label>
            <Select
              value={config.brand_voice}
              onChange={e => setConfig(c => ({ ...c, brand_voice: e.target.value }))}
            >
              {VOICES.map(v => <option key={v} value={v}>{v.charAt(0).toUpperCase() + v.slice(1)}</option>)}
            </Select>
          </div>
          <div>
            <Label>Langue</Label>
            <Select
              value={config.default_language}
              onChange={e => setConfig(c => ({ ...c, default_language: e.target.value }))}
            >
              {LANGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </Select>
          </div>
          <div>
            <Label>Style emoji</Label>
            <Select
              value={config.emoji_style}
              onChange={e => setConfig(c => ({ ...c, emoji_style: e.target.value }))}
            >
              {EMOJIS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </Select>
          </div>
        </div>
      </Card>

      {/* Style DALL-E */}
      <Card className="space-y-4">
        <h3 className="font-semibold text-gray-900 text-sm">🎨 Style visuel DALL-E 3</h3>
        <div>
          <Label>Description du style d'image</Label>
          <Textarea
            rows={2}
            value={config.image_style}
            onChange={e => setConfig(c => ({ ...c, image_style: e.target.value }))}
            placeholder="commercial product photo, clean background, professional lighting"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Couleurs</Label>
            <Input
              value={config.image_colors || ''}
              onChange={e => setConfig(c => ({ ...c, image_colors: e.target.value }))}
              placeholder="bleu, blanc, or..."
            />
          </div>
          <div>
            <Label>Filigrane</Label>
            <Input
              value={config.watermark_text || ''}
              onChange={e => setConfig(c => ({ ...c, watermark_text: e.target.value }))}
              placeholder="@maboutique"
            />
          </div>
        </div>
      </Card>

      {/* Hashtags */}
      <Card className="space-y-3">
        <h3 className="font-semibold text-gray-900 text-sm"># Hashtags par défaut</h3>
        <div className="flex flex-wrap gap-2 min-h-[32px]">
          {(config.hashtags || []).map((tag, i) => (
            <span key={i} className="flex items-center gap-1 bg-violet-50 border border-violet-200 text-violet-700 rounded-full px-3 py-1 text-xs font-semibold">
              #{tag}
              <button
                onClick={() => setConfig(c => ({ ...c, hashtags: c.hashtags.filter((_, j) => j !== i) }))}
                className="text-violet-400 hover:text-violet-700 ml-1 leading-none"
              >
                ×
              </button>
            </span>
          ))}
          {(config.hashtags || []).length === 0 && (
            <span className="text-xs text-gray-400 italic">Aucun hashtag configuré</span>
          )}
        </div>
        <div className="flex gap-2">
          <Input
            className="flex-1"
            value={newHashtag}
            onChange={e => setNewHashtag(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addHashtag()}
            placeholder="#tunisie, #shopping..."
          />
          <button
            onClick={addHashtag}
            className="bg-violet-600 text-white rounded-xl px-4 py-2 text-sm font-semibold hover:bg-violet-700 transition flex-shrink-0"
          >
            + Ajouter
          </button>
        </div>
      </Card>

      {/* Planification auto */}
      <Card className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-gray-900 text-sm">🗓️ Planification automatique</h3>
          <ToggleSwitch
            checked={config.auto_schedule}
            onChange={v => setConfig(c => ({ ...c, auto_schedule: v }))}
          />
        </div>

        {config.auto_schedule && (
          <div className="space-y-4 pt-3 border-t border-gray-100">
            <div>
              <Label>Horaires de publication</Label>
              <div className="space-y-2">
                {(config.post_times || []).map((t, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <input
                      type="time"
                      className="border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400"
                      value={t}
                      onChange={e => setConfig(c => ({
                        ...c,
                        post_times: c.post_times.map((x, j) => j === i ? e.target.value : x),
                      }))}
                    />
                    {(config.post_times || []).length > 1 && (
                      <button
                        onClick={() => setConfig(c => ({ ...c, post_times: c.post_times.filter((_, j) => j !== i) }))}
                        className="text-red-400 hover:text-red-600 border border-red-200 rounded-lg px-2 py-1.5 text-sm"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                ))}
                {(config.post_times || []).length < 5 && (
                  <button
                    onClick={() => setConfig(c => ({ ...c, post_times: [...(c.post_times || []), '20:00'] }))}
                    className="text-xs text-violet-600 border border-violet-200 rounded-xl px-3 py-1.5 hover:bg-violet-50 transition"
                  >
                    + Ajouter un horaire
                  </button>
                )}
              </div>
            </div>

            <div>
              <Label>Jours actifs</Label>
              <div className="flex flex-wrap gap-2">
                {DAYS_FR.map((d, i) => {
                  const active = (config.post_days || [0, 1, 2, 3, 4, 5, 6]).includes(i);
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => setConfig(c => ({
                        ...c,
                        post_days: active
                          ? c.post_days.filter(x => x !== i)
                          : [...(c.post_days || []), i].sort(),
                      }))}
                      className={`w-10 h-10 rounded-xl text-xs font-bold border-2 transition-all ${
                        active
                          ? 'bg-violet-600 border-violet-600 text-white'
                          : 'bg-white border-gray-200 text-gray-500 hover:border-violet-300'
                      }`}
                    >
                      {d}
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <Label>Max publications / jour</Label>
              <input
                type="number"
                className="w-24 border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400"
                value={config.max_posts_per_day}
                min={1}
                max={10}
                onChange={e => setConfig(c => ({ ...c, max_posts_per_day: parseInt(e.target.value) || 1 }))}
              />
            </div>
          </div>
        )}
      </Card>

      <BtnPrimary className="w-full py-3.5" onClick={save} disabled={saving}>
        {saving ? <><span className="animate-spin inline-block">⏳</span> Sauvegarde...</> : <><span>💾</span> Sauvegarder les préférences</>}
      </BtnPrimary>
    </div>
  );
}

/* ─── Page principale ────────────────────────────────────────────────────── */
export default function SocialBroadcast() {
  const [tab, setTab]               = useState(0);
  const [socialStatus, setSocialStatus] = useState({ instagram: {}, facebook: {}, tiktok: {} });
  const [toast, setToast]           = useState({ msg: '', type: 'success' });

  const TABS = [
    { label: '🚀 Publier',     id: 0 },
    { label: '⏰ Planifier',   id: 1 },
    { label: '📋 Historique',  id: 2 },
    { label: '⚙️ Préférences', id: 3 },
  ];

  useEffect(() => {
    api('social/status')
      .then(setSocialStatus)
      .catch(e => console.error('social status:', e));
  }, []);

  const showToast  = useCallback((msg, type = 'success') => setToast({ msg, type }), []);
  const closeToast = useCallback(() => setToast({ msg: '' }), []);

  const connectedCount = Object.values(socialStatus).filter(s => s?.connected).length;

  return (
    <div className="space-y-5">
      <Toast msg={toast.msg} type={toast.type} onClose={closeToast} />

      {/* ── En-tête ── */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">📣 Publication IA — Réseaux Sociaux</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            GPT-4o génère vos annonces · DALL-E 3 crée vos visuels · Publication automatique multi-réseau
          </p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          {NETWORKS.map(n => (
            <NetworkBadge key={n.id} network={n.id} connected={socialStatus[n.id]?.connected} />
          ))}
          {connectedCount === 0 && (
            <a
              href="/settings"
              className="text-xs text-amber-600 font-semibold border border-amber-200 bg-amber-50 rounded-xl px-3 py-1.5 hover:bg-amber-100 transition"
            >
              ⚙️ Connecter les réseaux →
            </a>
          )}
        </div>
      </div>

      {/* ── Bannière IA ── */}
      <div className="bg-gradient-to-r from-violet-600 to-pink-500 rounded-2xl p-4 sm:p-5 text-white">
        <div className="flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex-1">
            <p className="font-bold text-base sm:text-lg">🤖 Système de publication automatique IA</p>
            <p className="text-violet-100 text-xs sm:text-sm mt-1">
              Décrivez votre annonce en quelques mots — l'IA rédige la légende, génère le visuel et publie sur tous vos réseaux en un clic.
            </p>
          </div>
          <div className="flex gap-3 text-center flex-shrink-0">
            <div className="bg-white/20 rounded-xl px-4 py-2">
              <p className="font-bold text-xl">{connectedCount}</p>
              <p className="text-xs text-violet-100">Réseau{connectedCount !== 1 ? 'x' : ''}</p>
            </div>
            <div className="bg-white/20 rounded-xl px-4 py-2">
              <p className="font-bold text-xl">GPT-4o</p>
              <p className="text-xs text-violet-100">+ DALL-E 3</p>
            </div>
          </div>
        </div>
      </div>

      {/* ── Tabs ── */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-xl overflow-x-auto scrollbar-hide">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-shrink-0 px-3 sm:px-4 py-2 text-xs sm:text-sm font-semibold rounded-lg transition-all whitespace-nowrap ${
              tab === t.id
                ? 'bg-white shadow-sm text-gray-900'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Contenu ── */}
      {tab === 0 && <PublishTab socialStatus={socialStatus} onToast={showToast} />}
      {tab === 1 && <ScheduleTab onToast={showToast} />}
      {tab === 2 && <HistoryTab onToast={showToast} />}
      {tab === 3 && <PrefsTab onToast={showToast} />}
    </div>
  );
}
