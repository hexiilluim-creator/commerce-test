// src/pages/Conversations.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Conversations multi-canaux — Layout type WhatsApp.
// • Supporte WhatsApp, Instagram, Facebook, TikTok (social_agent BLOC 10)
// • Filtre par canal (tabs: Tous / WA / IG / FB / TT)
// • Icône canal sur chaque conversation
// • Contrôle IA : sourdine globale + prise de main per-client
// • Mobile : liste OU chat empilés | Desktop : 2 panneaux côte à côte
// ─────────────────────────────────────────────────────────────────────────────
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useStore } from '../context/StoreContext';
import { useTranslation } from 'react-i18next';

// ── FSM colors ────────────────────────────────────────────────────────────────
const FSM_COLORS = {
  idle: 'bg-gray-100 text-gray-600',
  browsing: 'bg-blue-100 text-blue-700',
  product_shown: 'bg-yellow-100 text-yellow-700',
  awaiting_confirm: 'bg-orange-100 text-orange-700',
  awaiting_delivery: 'bg-purple-100 text-purple-700',
  order_created: 'bg-green-100 text-green-700',
};

const MSG_ICONS = { text: '💬', image: '📷', audio: '🎤', interactive: '🔘' };

// ── Channel definitions ────────────────────────────────────────────────────────
const CHANNELS = [
  { id: 'all',       label: 'Tous',       icon: '🗂️',  color: 'bg-gray-100 text-gray-700',    badge: '' },
  { id: 'whatsapp',  label: 'WhatsApp',   icon: '💬',  color: 'bg-green-100 text-green-700',   badge: '🟢' },
  { id: 'instagram', label: 'Instagram',  icon: '📸',  color: 'bg-pink-100 text-pink-700',     badge: '🌸' },
  { id: 'facebook',  label: 'Facebook',   icon: '👤',  color: 'bg-blue-100 text-blue-700',     badge: '🔵' },
  { id: 'tiktok',    label: 'TikTok',     icon: '🎵',  color: 'bg-black/10 text-gray-800',     badge: '⚫' },
];

function channelIcon(channel) {
  const c = CHANNELS.find(x => x.id === channel);
  return c ? c.icon : '💬';
}

function channelColor(channel) {
  const c = CHANNELS.find(x => x.id === channel);
  return c ? c.color : 'bg-gray-100 text-gray-600';
}

// ── Agent status pill ─────────────────────────────────────────────────────────
function AgentStatusPill({ agentStatus, onMute, onUnmute }) {
  if (!agentStatus) return null;
  const { ai_mode, mute } = agentStatus;

  if (ai_mode === 'muted') {
    return (
      <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-3 py-1.5 text-xs">
        <span className="text-red-600 font-semibold">🔇 IA en sourdine</span>
        <span className="text-red-400">{mute?.remaining_minutes}min restantes</span>
        <button onClick={onUnmute}
          className="ml-1 text-red-600 hover:text-red-800 font-bold">✕ Reprendre</button>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-1 bg-green-50 border border-green-200 rounded-xl px-3 py-1.5 text-xs text-green-700">
        <span className="w-2 h-2 rounded-full bg-green-400 inline-block" />
        IA active
      </div>
      <button onClick={onMute}
        className="text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded-xl px-3 py-1.5 hover:bg-gray-50 transition">
        🔇 Sourdine 30min
      </button>
    </div>
  );
}

// ── Takeover indicator (per-customer) ─────────────────────────────────────────
function TakeoverBadge({ agentStatus, customer }) {
  if (!agentStatus || !customer) return null;
  const phone = customer.whatsapp_phone || customer.social_sender_id || '';
  const entry = agentStatus.takeovers?.find(t =>
    phone.endsWith(t.customer_phone) || t.customer_phone === phone
  );
  if (!entry) return null;
  return (
    <div className="inline-flex items-center gap-1 text-xs bg-amber-50 border border-amber-200 text-amber-700 rounded-full px-2 py-0.5">
      ✋ Prise de main · {entry.remaining_minutes}min
    </div>
  );
}

export default function Conversations() {
  const { api } = useStore();
  const { t, i18n } = useTranslation();
  const isRTL = i18n.language === 'ar';
  const dateLocale = i18n.language === 'ar' ? 'ar-SA' : i18n.language === 'en' ? 'en-GB' : 'fr-TN';

  // ── State ──────────────────────────────────────────────────────────────────
  const [customers, setCustomers] = useState([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState(null);
  const [messages, setMessages] = useState([]);
  const [fsmLog, setFsmLog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingCustomers, setLoadingCustomers] = useState(false);
  const [msgTab, setMsgTab] = useState('messages');
  const [q, setQ] = useState('');
  const [channelFilter, setChannelFilter] = useState('all');

  // Agent control
  const [agentStatus, setAgentStatus] = useState(null);
  const [muteMinutes, setMuteMinutes] = useState(30);
  const [showMutePanel, setShowMutePanel] = useState(false);
  const [takeoverMinutes, setTakeoverMinutes] = useState(120);
  const [actionMsg, setActionMsg] = useState('');

  // Manual reply
  const [manualReply, setManualReply] = useState('');
  const [sendingReply, setSendingReply] = useState(false);
  const messagesEndRef = useRef(null);

  // ── Load ───────────────────────────────────────────────────────────────────
  useEffect(() => { loadCustomers(); }, [q, channelFilter]); // eslint-disable-line

  useEffect(() => {
    loadAgentStatus();
    const interval = setInterval(loadAgentStatus, 30000);
    return () => clearInterval(interval);
  }, []); // eslint-disable-line

  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  const loadCustomers = async () => {
    setLoadingCustomers(true);
    try {
      const params = { q: q || undefined };
      if (channelFilter !== 'all') params.channel = channelFilter;
      const { data } = await api.get('/conversations/', { params });
      setCustomers(data.items || []);
      setTotal(data.total || 0);
    } catch { /* empty list */ }
    finally {
      setLoadingCustomers(false);
      setLoading(false);
    }
  };

  const selectCustomer = async (customer) => {
    setSelected(customer);
    setMessages([]);
    setFsmLog([]);
    setManualReply('');
    try {
      const [msgRes, fsmRes] = await Promise.all([
        api.get(`/conversations/${customer.id}/messages`),
        api.get(`/conversations/${customer.id}/fsm-log`),
      ]);
      setMessages(msgRes.data.messages || []);
      setFsmLog(fsmRes.data || []);
    } catch { /* ignore */ }
  };

  // ── Agent control ──────────────────────────────────────────────────────────
  const loadAgentStatus = async () => {
    try {
      const { data } = await api.get('/whatsapp/agent/status');
      setAgentStatus(data);
    } catch { /* Redis may be unavailable */ }
  };

  const handleMute = async () => {
    try {
      await api.post('/whatsapp/agent/mute', { minutes: muteMinutes });
      setActionMsg(`🔇 IA en sourdine pour ${muteMinutes} min`);
      setShowMutePanel(false);
      await loadAgentStatus();
    } catch { setActionMsg('Erreur lors de la sourdine'); }
    setTimeout(() => setActionMsg(''), 4000);
  };

  const handleUnmute = async () => {
    try {
      await api.delete('/whatsapp/agent/mute');
      setActionMsg('✅ IA réactivée');
      await loadAgentStatus();
    } catch { setActionMsg('Erreur lors de la réactivation'); }
    setTimeout(() => setActionMsg(''), 3000);
  };

  const handleTakeover = async (customer) => {
    const phone = customer.whatsapp_phone || customer.social_sender_id;
    if (!phone) return;
    try {
      await api.post(`/whatsapp/agent/takeover/${encodeURIComponent(phone)}`, { minutes: takeoverMinutes });
      setActionMsg(`✋ Prise de main sur ${customer.name || phone} — ${takeoverMinutes}min`);
      await loadAgentStatus();
    } catch { setActionMsg('Erreur prise de main'); }
    setTimeout(() => setActionMsg(''), 4000);
  };

  const handleRelease = async (customer) => {
    const phone = customer.whatsapp_phone || customer.social_sender_id;
    if (!phone) return;
    try {
      await api.delete(`/whatsapp/agent/takeover/${encodeURIComponent(phone)}`);
      setActionMsg('🤖 IA reprend la main');
      await loadAgentStatus();
    } catch { setActionMsg('Erreur lors du retour IA'); }
    setTimeout(() => setActionMsg(''), 3000);
  };

  // ── Manual reply ───────────────────────────────────────────────────────────
  const sendManualReply = async () => {
    if (!manualReply.trim() || !selected) return;
    setSendingReply(true);
    try {
      await api.post(`/conversations/${selected.id}/reply`, { text: manualReply });
      setManualReply('');
      // Refresh messages
      const { data } = await api.get(`/conversations/${selected.id}/messages`);
      setMessages(data.messages || []);
    } catch {
      setActionMsg('Erreur envoi — répondez directement depuis votre téléphone');
    } finally { setSendingReply(false); }
    setTimeout(() => setActionMsg(''), 4000);
  };

  // ── Helpers ────────────────────────────────────────────────────────────────
  const timeAgo = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    const diff = Math.floor((new Date() - d) / 1000);
    if (diff < 60) return `${diff}s`;
    if (diff < 3600) return `${Math.floor(diff / 60)}min`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    return d.toLocaleDateString(dateLocale);
  };

  const isTakenOver = (customer) => {
    const phone = customer.whatsapp_phone || customer.social_sender_id || '';
    return agentStatus?.takeovers?.some(t =>
      phone.endsWith(t.customer_phone) || t.customer_phone === phone
    );
  };

  return (
    <div
      className="flex flex-col md:flex-row md:gap-4 h-[calc(100vh-8rem)]"
      dir={isRTL ? 'rtl' : 'ltr'}
    >
      {/* ───── Left panel ──────────────────────────────────────────────────── */}
      <div
        className={`${
          selected ? 'hidden md:flex' : 'flex'
        } flex-col w-full md:w-72 shrink-0 premium-card overflow-hidden`}
      >
        {/* Header + search */}
        <div className="p-3 md:p-4 border-b border-gray-50 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold text-gray-900 text-sm">
              {t('conversations.title') || 'Conversations'}
              <span className="ml-2 text-xs text-gray-400 font-normal">({total})</span>
            </h2>
            <button
              onClick={loadCustomers}
              className="text-gray-400 hover:text-gray-600 text-lg"
              title="Actualiser"
            >↻</button>
          </div>

          {/* Search */}
          <input
            className="w-full text-sm border border-gray-200 rounded-xl px-3 py-2 outline-none focus:ring-2 focus:ring-indigo-100"
            placeholder={t('conversations.searchPlaceholder') || 'Rechercher…'}
            value={q}
            onChange={e => setQ(e.target.value)}
          />

          {/* Channel filter tabs */}
          <div className="flex gap-1 overflow-x-auto pb-1 scrollbar-hide">
            {CHANNELS.map(ch => (
              <button
                key={ch.id}
                onClick={() => setChannelFilter(ch.id)}
                className={`flex-shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                  channelFilter === ch.id
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-gray-500 hover:bg-gray-100'
                }`}
              >
                {ch.icon} {ch.label}
              </button>
            ))}
          </div>

          {/* Agent status */}
          <AgentStatusPill
            agentStatus={agentStatus}
            onMute={() => setShowMutePanel(true)}
            onUnmute={handleUnmute}
          />

          {/* Mute duration panel */}
          {showMutePanel && (
            <div className="bg-gray-50 rounded-xl p-3 space-y-2">
              <p className="text-xs font-medium text-gray-700">Durée de la sourdine</p>
              <div className="flex gap-2 flex-wrap">
                {[15, 30, 60, 120].map(m => (
                  <button key={m}
                    onClick={() => setMuteMinutes(m)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-semibold border transition ${
                      muteMinutes === m
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'border-gray-200 text-gray-600 hover:bg-gray-100'
                    }`}
                  >{m}min</button>
                ))}
              </div>
              <div className="flex gap-2">
                <button onClick={handleMute}
                  className="flex-1 bg-red-500 hover:bg-red-600 text-white rounded-xl py-1.5 text-xs font-semibold">
                  🔇 Activer la sourdine
                </button>
                <button onClick={() => setShowMutePanel(false)}
                  className="px-3 text-gray-500 hover:bg-gray-100 rounded-xl text-xs">
                  Annuler
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Customer list */}
        <div className="flex-1 overflow-y-auto divide-y divide-gray-50">
          {loading || loadingCustomers ? (
            <p className="text-center text-gray-400 text-sm py-8">{t('common.loading')}</p>
          ) : customers.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 px-6 text-center gap-3">
              <span className="text-5xl">
                {channelFilter === 'instagram' ? '📸' :
                 channelFilter === 'facebook' ? '👤' :
                 channelFilter === 'tiktok' ? '🎵' : '💬'}
              </span>
              <p className="font-semibold text-gray-700">
                {channelFilter !== 'all'
                  ? `Aucune conversation ${CHANNELS.find(c => c.id === channelFilter)?.label}`
                  : t('conversations.empty')}
              </p>
              <p className="text-gray-400 text-sm max-w-xs">
                {channelFilter === 'whatsapp' || channelFilter === 'all'
                  ? (t('conversations.emptyHint') || 'Connectez WhatsApp pour recevoir des messages.')
                  : `Configurez ${CHANNELS.find(c => c.id === channelFilter)?.label} dans les paramètres.`}
              </p>
              <a href="/settings"
                className="mt-2 bg-indigo-500 hover:bg-indigo-600 text-white text-sm px-4 py-2 rounded-xl inline-flex items-center gap-2">
                ⚙️ Paramètres canaux
              </a>
            </div>
          ) : customers.map(c => (
            <div
              key={c.id}
              onClick={() => selectCustomer(c)}
              className={`px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors ${
                selected?.id === c.id ? 'bg-indigo-50' : ''
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1 flex items-start gap-2">
                  {/* Channel icon */}
                  <span className={`text-base shrink-0 mt-0.5`} title={c.channel || 'whatsapp'}>
                    {channelIcon(c.channel || 'whatsapp')}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-gray-900 text-sm truncate">
                      {c.name || c.whatsapp_phone || c.social_sender_id}
                    </p>
                    {c.name && (
                      <p className="text-xs text-gray-400 truncate">
                        {c.channel !== 'whatsapp' ? c.social_sender_id : c.whatsapp_phone}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className="text-xs text-gray-400">{timeAgo(c.last_message_at)}</span>
                  {isTakenOver(c) && (
                    <span className="text-xs text-amber-600 font-semibold">✋ Manuel</span>
                  )}
                </div>
              </div>
              <div className="mt-1 flex items-center gap-2">
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${FSM_COLORS[c.fsm_state] || FSM_COLORS.idle}`}>
                  {c.fsm_state || 'idle'}
                </span>
                <span className={`text-xs px-1.5 py-0.5 rounded-full ${channelColor(c.channel || 'whatsapp')}`}>
                  {CHANNELS.find(ch => ch.id === (c.channel || 'whatsapp'))?.label || 'WA'}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ───── Right panel — conversation ──────────────────────────────────── */}
      <div
        className={`${
          selected ? 'flex' : 'hidden md:flex'
        } flex-1 flex-col premium-card overflow-hidden h-full mt-3 md:mt-0`}
      >
        {!selected ? (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <p className="text-4xl mb-2">💬</p>
              <p>{t('conversations.selectPrompt') || 'Sélectionnez une conversation'}</p>
            </div>
          </div>
        ) : (
          <>
            {/* Customer header */}
            <div className="px-4 py-3 border-b border-gray-50 flex items-center justify-between gap-3">
              {/* Back button (mobile) */}
              <button
                onClick={() => setSelected(null)}
                className="md:hidden text-gray-400 hover:text-gray-600 text-xl mr-1"
              >←</button>

              <div className="flex items-center gap-3 flex-1 min-w-0">
                <div className="flex flex-col gap-0.5 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{channelIcon(selected.channel || 'whatsapp')}</span>
                    <span className="font-semibold text-gray-900 text-sm truncate">
                      {selected.name || selected.whatsapp_phone || selected.social_sender_id}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${channelColor(selected.channel || 'whatsapp')}`}>
                      {CHANNELS.find(ch => ch.id === (selected.channel || 'whatsapp'))?.label}
                    </span>
                    <TakeoverBadge agentStatus={agentStatus} customer={selected} />
                  </div>
                </div>
              </div>

              {/* Agent control for this customer */}
              <div className="flex items-center gap-2 shrink-0">
                {isTakenOver(selected) ? (
                  <button onClick={() => handleRelease(selected)}
                    className="text-xs bg-green-500 hover:bg-green-600 text-white px-3 py-1.5 rounded-xl font-semibold transition">
                    🤖 Rendre à l'IA
                  </button>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <select
                      value={takeoverMinutes}
                      onChange={e => setTakeoverMinutes(Number(e.target.value))}
                      className="text-xs border border-gray-200 rounded-lg px-1.5 py-1 outline-none"
                    >
                      {[30, 60, 120, 240].map(m => (
                        <option key={m} value={m}>{m}min</option>
                      ))}
                    </select>
                    <button onClick={() => handleTakeover(selected)}
                      className="text-xs bg-amber-500 hover:bg-amber-600 text-white px-3 py-1.5 rounded-xl font-semibold transition">
                      ✋ Prendre la main
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Action feedback */}
            {actionMsg && (
              <div className="mx-4 mt-2 bg-indigo-50 border border-indigo-100 text-indigo-700 rounded-xl px-3 py-2 text-xs">
                {actionMsg}
              </div>
            )}

            {/* Tabs */}
            <div className="flex gap-1 px-3 md:px-4 py-2 border-b border-gray-50 overflow-x-auto">
              {[
                ['messages', `💬 ${t('conversations.tabMessages') || 'Messages'}`],
                ['fsm', `🔄 ${t('conversations.tabFSM') || 'FSM'}`],
              ].map(([id, label]) => (
                <button
                  key={id}
                  onClick={() => setMsgTab(id)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors whitespace-nowrap ${
                    msgTab === id ? 'bg-indigo-50 text-indigo-700' : 'text-gray-500 hover:bg-gray-50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* Messages */}
            {msgTab === 'messages' && (
              <div className="flex-1 overflow-y-auto p-3 md:p-4 space-y-3">
                {messages.length === 0 ? (
                  <div className="text-center text-gray-400 text-sm py-8 space-y-2">
                    <p className="text-2xl">
                      {channelIcon(selected.channel || 'whatsapp')}
                    </p>
                    <p>{t('conversations.noMessages') || 'Aucun message'}</p>
                    {selected.channel && selected.channel !== 'whatsapp' && (
                      <p className="text-xs text-gray-300 max-w-xs mx-auto">
                        Les messages {CHANNELS.find(c => c.id === selected.channel)?.label} apparaissent
                        ici lorsque l'intégration est configurée.
                      </p>
                    )}
                  </div>
                ) : messages.map(m => (
                  <div key={m.id} className="space-y-1">
                    {/* Client message */}
                    <div className="flex justify-start">
                      <div className="bg-gray-100 rounded-2xl rounded-tl-none px-4 py-2.5 max-w-[85%] md:max-w-xs">
                        <p className="text-xs text-gray-400 mb-1">
                          {MSG_ICONS[m.message_type]} {m.message_type}
                        </p>
                        <p className="text-sm text-gray-800 break-words">{m.content || '[media]'}</p>
                        {m.ai_analysis && (
                          <div className="mt-1 text-xs text-purple-600 bg-purple-50 rounded-lg px-2 py-1">
                            🤖 {m.ai_analysis.type} — {m.ai_analysis.description_fr || ''}
                          </div>
                        )}
                      </div>
                    </div>
                    {/* AI / manual response */}
                    {m.ai_response && (
                      <div className="flex justify-end">
                        <div className={`rounded-2xl rounded-tr-none px-4 py-2.5 max-w-[85%] md:max-w-xs ${
                          m.is_manual_reply
                            ? 'bg-amber-500 text-white'
                            : 'bg-indigo-600 text-white'
                        }`}>
                          <p className="text-xs text-white/70 mb-1">
                            {m.is_manual_reply ? '✋ Vous' : '🤖 Agent'}
                          </p>
                          <p className="text-sm break-words">{m.ai_response}</p>
                        </div>
                      </div>
                    )}
                    <p className="text-xs text-gray-300 text-center">
                      {new Date(m.created_at).toLocaleString(dateLocale)}
                    </p>
                  </div>
                ))}
                <div ref={messagesEndRef} />
              </div>
            )}

            {/* FSM log */}
            {msgTab === 'fsm' && (
              <div className="flex-1 overflow-y-auto p-3 md:p-4 space-y-2">
                {fsmLog.length === 0 ? (
                  <p className="text-center text-gray-400 text-sm py-8">
                    {t('conversations.noFSM') || 'Aucune transition FSM'}
                  </p>
                ) : fsmLog.map(log => (
                  <div
                    key={log.id}
                    className="flex flex-wrap items-center gap-2 bg-gray-50 rounded-xl px-3 py-2.5 text-sm"
                  >
                    <span className={`px-2 py-0.5 rounded-full text-xs ${FSM_COLORS[log.from_state] || 'bg-gray-100 text-gray-500'}`}>
                      {log.from_state || '—'}
                    </span>
                    <span className="text-gray-400">→</span>
                    <span className={`px-2 py-0.5 rounded-full text-xs ${FSM_COLORS[log.to_state] || 'bg-gray-100 text-gray-500'}`}>
                      {log.to_state}
                    </span>
                    <span className="text-gray-500 text-xs">{log.trigger}</span>
                    <span className="ml-auto text-xs text-gray-400 shrink-0">
                      {new Date(log.created_at).toLocaleString(dateLocale)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Manual reply box — visible only when in takeover mode */}
            {isTakenOver(selected) && (
              <div className="border-t border-gray-100 p-3 md:p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs text-amber-600 font-semibold">✋ Réponse manuelle</span>
                  <span className="text-xs text-gray-400">
                    via {CHANNELS.find(c => c.id === (selected.channel || 'whatsapp'))?.label}
                  </span>
                </div>
                <div className="flex gap-2">
                  <textarea
                    value={manualReply}
                    onChange={e => setManualReply(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        sendManualReply();
                      }
                    }}
                    placeholder="Tapez votre réponse… (Entrée pour envoyer)"
                    rows={2}
                    className="flex-1 border border-gray-200 rounded-xl px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-amber-100 resize-none"
                  />
                  <button
                    onClick={sendManualReply}
                    disabled={!manualReply.trim() || sendingReply}
                    className="bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white px-4 rounded-xl font-semibold text-sm transition"
                  >
                    {sendingReply ? '…' : '↗'}
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

