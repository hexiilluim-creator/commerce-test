import React, { useCallback, useEffect, useState } from 'react';
import axiosApi, { extractErrorMessage } from '../api';
import { useConfirm } from '../context/ConfirmContext';
import { useStore } from '../context/StoreContext';
import { formatMoney } from '../utils/currency';

/* ─── API helper (compat) — délègue à l'instance Axios centralisée ──────── */
const api = async (path, opts = {}) => {
  const method = (opts.method || 'GET').toUpperCase();
  let data = opts.body;
  if (typeof data === 'string') {
    try { data = JSON.parse(data); } catch { /* keep raw */ }
  }
  try {
    // Bug9 FIX: remove leading '/' from url so Axios appends to baseURL (/api/v1)
    // Previously: url: `/appointments${path}` with path='/' → url='/appointments/'
    // This accidentally worked, but path='/services' → url='/appointments/services'
    // The leading '/' caused Axios to replace baseURL entirely on some versions.
    // Fix: use relative path without leading slash → appended to baseURL correctly.
    const cleanPath = path.startsWith('/') ? path.slice(1) : path;
    const url = cleanPath ? `appointments/${cleanPath}` : 'appointments/';
    const res = await axiosApi.request({
      url,
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
const DAYS = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday'];
const DAY_FR = { monday:'Lundi', tuesday:'Mardi', wednesday:'Mercredi',
  thursday:'Jeudi', friday:'Vendredi', saturday:'Samedi', sunday:'Dimanche' };
const STATUS_COLORS = {
  pending:   { bg:'#2a2400', border:'#b45309', text:'#fbbf24', label:'En attente' },
  confirmed: { bg:'#052e16', border:'#166534', text:'#4ade80', label:'Confirmé' },
  cancelled: { bg:'#2d0000', border:'#7f1d1d', text:'#f87171', label:'Annulé' },
  completed: { bg:'#0c1a2e', border:'#1e3a5f', text:'#60a5fa', label:'Terminé' },
  no_show:   { bg:'#1a0a00', border:'#7c2d12', text:'#fb923c', label:'No-show' },
};
const TABS = ['Agenda', 'Services', 'Disponibilités', 'Paramètres'];

/* ─── Styles ─────────────────────────────────────────────────────────────── */
const S = {
  page:    { minHeight:'100vh', background:'#0a0f0d', color:'#e8f5ec', fontFamily:"'DM Sans',sans-serif", padding:'28px' },
  card:    { background:'#141f18', border:'1px solid rgba(37,211,102,0.15)', borderRadius:16, padding:24 },
  input:   { background:'#0d1910', border:'1px solid rgba(37,211,102,0.2)', borderRadius:10, padding:'10px 14px', color:'#e8f5ec', fontSize:14, width:'100%', outline:'none' },
  select:  { background:'#0d1910', border:'1px solid rgba(37,211,102,0.2)', borderRadius:10, padding:'10px 14px', color:'#e8f5ec', fontSize:14, width:'100%', outline:'none' },
  btnGreen:{ background:'#25D366', color:'#000', border:'none', borderRadius:10, padding:'10px 22px', fontSize:14, fontWeight:700, cursor:'pointer' },
  btnOutline:{ background:'transparent', color:'#e8f5ec', border:'1px solid rgba(37,211,102,0.25)', borderRadius:10, padding:'10px 18px', fontSize:13, cursor:'pointer' },
  btnDanger:{ background:'transparent', color:'#f87171', border:'1px solid #7f1d1d', borderRadius:10, padding:'8px 14px', fontSize:12, cursor:'pointer' },
  label:   { fontSize:12, color:'#7aab88', marginBottom:6, display:'block', fontWeight:600 },
  h2:      { fontFamily:"'Syne',sans-serif", fontWeight:800, fontSize:22, marginBottom:0 },
  h3:      { fontFamily:"'Syne',sans-serif", fontWeight:700, fontSize:16 },
  muted:   { color:'#7aab88', fontSize:13 },
  badge:   (st) => ({
    background: STATUS_COLORS[st]?.bg || '#1a1a1a',
    border: `1px solid ${STATUS_COLORS[st]?.border || '#444'}`,
    color: STATUS_COLORS[st]?.text || '#aaa',
    borderRadius:100, padding:'3px 11px', fontSize:12, fontWeight:700,
  }),
  tag:     { background:'rgba(37,211,102,0.1)', border:'1px solid rgba(37,211,102,0.2)', color:'#25D366', borderRadius:100, padding:'3px 11px', fontSize:12, fontWeight:700 },
};

/* ─── Toast ──────────────────────────────────────────────────────────────── */
function Toast({ msg, type, onClose }) {
  useEffect(() => { if (msg) { const t = setTimeout(onClose, 3000); return () => clearTimeout(t); } }, [msg]);
  if (!msg) return null;
  return (
    <div style={{ position:'fixed', bottom:28, right:28, zIndex:9999,
      background: type === 'error' ? '#2d0000' : '#052e16',
      border: `1px solid ${type === 'error' ? '#7f1d1d' : '#166534'}`,
      borderRadius:14, padding:'14px 22px', color: type === 'error' ? '#f87171' : '#4ade80',
      fontWeight:600, fontSize:14, maxWidth:360, boxShadow:'0 8px 32px rgba(0,0,0,0.5)' }}>
      {type === 'error' ? '❌ ' : '✅ '}{msg}
    </div>
  );
}

/* ─── Modal ──────────────────────────────────────────────────────────────── */
function Modal({ open, onClose, title, children }) {
  if (!open) return null;
  return (
    <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.75)', zIndex:1000, display:'flex', alignItems:'center', justifyContent:'center', padding:24 }}
      onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={{ ...S.card, width:'100%', maxWidth:520, maxHeight:'85vh', overflowY:'auto' }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:20 }}>
          <h3 style={S.h3}>{title}</h3>
          <button onClick={onClose} style={{ background:'none', border:'none', color:'#7aab88', fontSize:20, cursor:'pointer' }}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

/* ─── Stat card ──────────────────────────────────────────────────────────── */
function StatCard({ icon, label, value, color = '#25D366' }) {
  return (
    <div style={{ ...S.card, display:'flex', alignItems:'center', gap:16 }}>
      <div style={{ width:48, height:48, borderRadius:14, background:`${color}18`, border:`1px solid ${color}30`, display:'flex', alignItems:'center', justifyContent:'center', fontSize:22, flexShrink:0 }}>{icon}</div>
      <div>
        <div style={{ fontSize:28, fontWeight:800, color, fontFamily:"'Syne',sans-serif", lineHeight:1 }}>{value}</div>
        <div style={S.muted}>{label}</div>
      </div>
    </div>
  );
}

/* ─── TAB: Agenda ────────────────────────────────────────────────────────── */
function AgendaTab({ services }) {
  const [appointments, setAppointments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [toast, setToast] = useState({ msg:'', type:'success' });
  const [form, setForm] = useState({
    service_id: '', scheduled_at: '', patient_name: '', notes: '', customer_phone: '',
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterStatus) params.set('status', filterStatus);
      params.set('limit', '100');
      const data = await api(`/?${params}`);
      setAppointments(data || []);
    } catch(e) {
      setToast({ msg: e.message, type:'error' });
    } finally { setLoading(false); }
  }, [filterStatus]);

  useEffect(() => { load(); }, [load]);

  const changeStatus = async (id, status) => {
    try {
      await api(`/${id}/status`, { method:'PATCH', body: JSON.stringify({ status }) });
      setToast({ msg:'Statut mis à jour', type:'success' });
      load();
    } catch(e) { setToast({ msg:e.message, type:'error' }); }
  };

  const createAppt = async () => {
    try {
      const payload = { ...form, service_id: form.service_id ? parseInt(form.service_id) : null };
      await api('/', { method:'POST', body: JSON.stringify(payload) });
      setToast({ msg:'RDV créé avec succès', type:'success' });
      setShowModal(false);
      setForm({ service_id:'', scheduled_at:'', patient_name:'', notes:'', customer_phone:'' });
      load();
    } catch(e) { setToast({ msg:e.message, type:'error' }); }
  };

  // Stats
  const stats = {
    total: appointments.length,
    confirmed: appointments.filter(a => a.status === 'confirmed').length,
    pending: appointments.filter(a => a.status === 'pending').length,
    today: appointments.filter(a => a.scheduled_date === new Date().toISOString().slice(0,10)).length,
  };

  return (
    <div>
      <Toast msg={toast.msg} type={toast.type} onClose={() => setToast({ msg:'' })} />
      <Modal open={showModal} onClose={() => setShowModal(false)} title="Nouveau RDV">
        <div style={{ display:'flex', flexDirection:'column', gap:16 }}>
          <div>
            <label style={S.label}>Téléphone client *</label>
            <input style={S.input} value={form.customer_phone} onChange={e=>setForm(f=>({...f,customer_phone:e.target.value}))} placeholder="+21612345678"/>
          </div>
          <div>
            <label style={S.label}>Service</label>
            <select style={S.select} value={form.service_id} onChange={e=>setForm(f=>({...f,service_id:e.target.value}))}>
              <option value="">— Aucun service spécifique —</option>
              {services.map(s=><option key={s.id} value={s.id}>{s.name} ({s.duration_min} min)</option>)}
            </select>
          </div>
          <div>
            <label style={S.label}>Date et heure *</label>
            <input type="datetime-local" style={S.input} value={form.scheduled_at} onChange={e=>setForm(f=>({...f,scheduled_at:e.target.value}))}/>
          </div>
          <div>
            <label style={S.label}>Nom du patient</label>
            <input style={S.input} value={form.patient_name} onChange={e=>setForm(f=>({...f,patient_name:e.target.value}))} placeholder="Prénom Nom"/>
          </div>
          <div>
            <label style={S.label}>Notes</label>
            <textarea style={{...S.input, height:80, resize:'vertical'}} value={form.notes} onChange={e=>setForm(f=>({...f,notes:e.target.value}))} placeholder="Notes optionnelles..."/>
          </div>
          <button style={S.btnGreen} onClick={createAppt}>Créer le RDV</button>
        </div>
      </Modal>

      {/* Stats */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(170px,1fr))', gap:16, marginBottom:24 }}>
        <StatCard icon="🗓️" label="Total RDV" value={stats.total} />
        <StatCard icon="✅" label="Confirmés" value={stats.confirmed} color="#4ade80" />
        <StatCard icon="⏳" label="En attente" value={stats.pending} color="#fbbf24" />
        <StatCard icon="📍" label="Aujourd'hui" value={stats.today} color="#60a5fa" />
      </div>

      {/* Toolbar */}
      <div style={{ display:'flex', gap:12, marginBottom:20, flexWrap:'wrap', alignItems:'center' }}>
        <select style={{ ...S.select, width:'auto', minWidth:160 }} value={filterStatus} onChange={e=>setFilterStatus(e.target.value)}>
          <option value="">Tous les statuts</option>
          {Object.entries(STATUS_COLORS).map(([k,v])=><option key={k} value={k}>{v.label}</option>)}
        </select>
        <button style={S.btnOutline} onClick={load}>🔄 Actualiser</button>
        <button style={S.btnGreen} onClick={()=>setShowModal(true)}>+ Nouveau RDV</button>
      </div>

      {/* List */}
      {loading ? (
        <div style={{ textAlign:'center', padding:48, color:'#7aab88' }}>Chargement...</div>
      ) : appointments.length === 0 ? (
        <div style={{ ...S.card, textAlign:'center', padding:48 }}>
          <div style={{ fontSize:40, marginBottom:12 }}>🗓️</div>
          <div style={S.muted}>Aucun rendez-vous trouvé</div>
        </div>
      ) : (
        <div style={{ display:'flex', flexDirection:'column', gap:12 }}>
          {appointments.map(appt => (
            <div key={appt.id} style={{ ...S.card, display:'flex', alignItems:'center', gap:20, flexWrap:'wrap' }}>
              {/* Date/Time */}
              <div style={{ minWidth:100, textAlign:'center' }}>
                <div style={{ fontSize:22, fontWeight:800, color:'#25D366', fontFamily:"'Syne',sans-serif" }}>
                  {appt.scheduled_time}
                </div>
                <div style={S.muted}>{appt.scheduled_date}</div>
              </div>

              {/* Info */}
              <div style={{ flex:1, minWidth:180 }}>
                <div style={{ fontWeight:700, fontSize:15, marginBottom:4 }}>
                  {appt.patient_name || `Client #${appt.customer_id}`}
                </div>
                {appt.service_id && (
                  <span style={S.tag}>
                    {services.find(s=>s.id===appt.service_id)?.name || `Service #${appt.service_id}`}
                  </span>
                )}
                {appt.notes && <div style={{ ...S.muted, marginTop:6 }}>{appt.notes}</div>}
              </div>

              {/* Duration */}
              <div style={{ textAlign:'center', minWidth:70 }}>
                <div style={{ fontSize:16, fontWeight:700 }}>⏱ {appt.duration_min}'</div>
                <div style={S.muted}>durée</div>
              </div>

              {/* Status + actions */}
              <div style={{ display:'flex', flexDirection:'column', gap:8, alignItems:'flex-end' }}>
                <span style={S.badge(appt.status)}>{STATUS_COLORS[appt.status]?.label}</span>
                <div style={{ display:'flex', gap:6 }}>
                  {appt.status === 'pending' && (
                    <button style={{ ...S.btnGreen, padding:'6px 12px', fontSize:12 }}
                      onClick={() => changeStatus(appt.id, 'confirmed')}>Confirmer</button>
                  )}
                  {['pending','confirmed'].includes(appt.status) && (
                    <button style={S.btnDanger} onClick={() => changeStatus(appt.id, 'cancelled')}>Annuler</button>
                  )}
                  {appt.status === 'confirmed' && (
                    <button style={{ ...S.btnOutline, padding:'6px 12px', fontSize:12 }}
                      onClick={() => changeStatus(appt.id, 'completed')}>✓ Terminé</button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─── TAB: Services ──────────────────────────────────────────────────────── */
function ServicesTab({ services, reload }) {
  const { store } = useStore();
  const money = (value) => formatMoney(value, store, 'fr');
  const confirm = useConfirm();
  const [showModal, setShowModal] = useState(false);
  const [editSvc, setEditSvc] = useState(null);
  const [form, setForm] = useState({ name:'', description:'', duration_min:30, price:'', is_active:true });
  const [toast, setToast] = useState({ msg:'', type:'success' });

  const openCreate = () => { setEditSvc(null); setForm({ name:'', description:'', duration_min:30, price:'', is_active:true }); setShowModal(true); };
  const openEdit = (s) => { setEditSvc(s); setForm({ name:s.name, description:s.description||'', duration_min:s.duration_min, price:s.price||'', is_active:s.is_active }); setShowModal(true); };

  const save = async () => {
    try {
      const payload = { ...form, duration_min:parseInt(form.duration_min), price:form.price?parseFloat(form.price):null };
      if (editSvc) await api(`/services/${editSvc.id}`, { method:'PUT', body: JSON.stringify(payload) });
      else await api('/services', { method:'POST', body: JSON.stringify(payload) });
      setToast({ msg: editSvc ? 'Service modifié' : 'Service créé', type:'success' });
      setShowModal(false); reload();
    } catch(e) { setToast({ msg:e.message, type:'error' }); }
  };

  const remove = async (id) => {
    if (!(await confirm('Supprimer ce service ?'))) return;
    try { await api(`/services/${id}`, { method:'DELETE' }); reload(); setToast({ msg:'Service supprimé', type:'success' }); }
    catch(e) { setToast({ msg:e.message, type:'error' }); }
  };

  return (
    <div>
      <Toast msg={toast.msg} type={toast.type} onClose={() => setToast({ msg:'' })} />
      <Modal open={showModal} onClose={() => setShowModal(false)} title={editSvc ? 'Modifier le service' : 'Nouveau service'}>
        <div style={{ display:'flex', flexDirection:'column', gap:14 }}>
          <div><label style={S.label}>Nom *</label><input style={S.input} value={form.name} onChange={e=>setForm(f=>({...f,name:e.target.value}))} placeholder="Ex: Consultation, Coupe, Bilan..."/></div>
          <div><label style={S.label}>Description</label><textarea style={{...S.input,height:70,resize:'vertical'}} value={form.description} onChange={e=>setForm(f=>({...f,description:e.target.value}))}/></div>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12 }}>
            <div><label style={S.label}>Durée (min)</label><input type="number" style={S.input} value={form.duration_min} onChange={e=>setForm(f=>({...f,duration_min:e.target.value}))}/></div>
            <div><label style={S.label}>Prix ({store?.currency || 'TND'})</label><input type="number" step="0.01" style={S.input} value={form.price} onChange={e=>setForm(f=>({...f,price:e.target.value}))} placeholder="Optionnel"/></div>
          </div>
          <label style={{ display:'flex', alignItems:'center', gap:10, cursor:'pointer' }}>
            <input type="checkbox" checked={form.is_active} onChange={e=>setForm(f=>({...f,is_active:e.target.checked}))}/>
            <span style={{ fontSize:14 }}>Service actif</span>
          </label>
          <button style={S.btnGreen} onClick={save}>{editSvc ? 'Enregistrer' : 'Créer le service'}</button>
        </div>
      </Modal>

      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:20 }}>
        <span style={S.muted}>{services.length} service(s) configuré(s)</span>
        <button style={S.btnGreen} onClick={openCreate}>+ Nouveau service</button>
      </div>

      {services.length === 0 ? (
        <div style={{ ...S.card, textAlign:'center', padding:48 }}>
          <div style={{ fontSize:36, marginBottom:12 }}>🩺</div>
          <div style={S.muted}>Aucun service — ajoutez votre premier service.</div>
        </div>
      ) : (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(240px,1fr))', gap:16 }}>
          {services.map(svc => (
            <div key={svc.id} style={{ ...S.card, position:'relative' }}>
              {!svc.is_active && <div style={{ position:'absolute', top:12, right:12, ...S.badge('cancelled'), fontSize:10 }}>Inactif</div>}
              <div style={{ fontSize:24, marginBottom:10 }}>🩺</div>
              <div style={{ fontFamily:"'Syne',sans-serif", fontWeight:700, fontSize:16, marginBottom:6 }}>{svc.name}</div>
              {svc.description && <div style={{ ...S.muted, marginBottom:10, fontSize:13 }}>{svc.description}</div>}
              <div style={{ display:'flex', gap:8, marginBottom:16, flexWrap:'wrap' }}>
                <span style={S.tag}>⏱ {svc.duration_min} min</span>
                {svc.price && <span style={S.tag}>💰 {money(svc.price)}</span>}
              </div>
              <div style={{ display:'flex', gap:8 }}>
                <button style={{ ...S.btnOutline, flex:1, padding:'8px' }} onClick={() => openEdit(svc)}>✏️ Modifier</button>
                <button style={S.btnDanger} onClick={() => remove(svc.id)}>🗑️</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─── TAB: Disponibilités ────────────────────────────────────────────────── */
function AvailabilityTab() {
  const [rules, setRules] = useState([]);
  const [form, setForm] = useState({ day_of_week:'monday', start_time:'09:00', end_time:'17:00' });
  const [toast, setToast] = useState({ msg:'', type:'success' });

  const load = async () => {
    try { setRules(await api('/availability') || []); }
    catch(e) { setToast({ msg:e.message, type:'error' }); }
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    try {
      await api('/availability', { method:'POST', body:JSON.stringify(form) });
      setToast({ msg:'Plage horaire ajoutée', type:'success' });
      load();
    } catch(e) { setToast({ msg:e.message, type:'error' }); }
  };

  const remove = async (id) => {
    try { await api(`/availability/${id}`, { method:'DELETE' }); load(); }
    catch(e) { setToast({ msg:e.message, type:'error' }); }
  };

  // Grouper par jour
  const byDay = DAYS.reduce((acc, d) => { acc[d] = rules.filter(r => r.day_of_week === d); return acc; }, {});

  return (
    <div>
      <Toast msg={toast.msg} type={toast.type} onClose={() => setToast({ msg:'' })} />

      {/* Add form */}
      <div style={{ ...S.card, marginBottom:24 }}>
        <div style={{ fontFamily:"'Syne',sans-serif", fontWeight:700, marginBottom:16 }}>➕ Ajouter une plage horaire</div>
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr auto', gap:12, alignItems:'flex-end' }}>
          <div>
            <label style={S.label}>Jour</label>
            <select style={S.select} value={form.day_of_week} onChange={e=>setForm(f=>({...f,day_of_week:e.target.value}))}>
              {DAYS.map(d=><option key={d} value={d}>{DAY_FR[d]}</option>)}
            </select>
          </div>
          <div>
            <label style={S.label}>Début</label>
            <input type="time" style={S.input} value={form.start_time} onChange={e=>setForm(f=>({...f,start_time:e.target.value}))}/>
          </div>
          <div>
            <label style={S.label}>Fin</label>
            <input type="time" style={S.input} value={form.end_time} onChange={e=>setForm(f=>({...f,end_time:e.target.value}))}/>
          </div>
          <button style={S.btnGreen} onClick={create}>Ajouter</button>
        </div>
      </div>

      {/* Calendar grid */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(160px,1fr))', gap:14 }}>
        {DAYS.map(day => (
          <div key={day} style={{ ...S.card, padding:16 }}>
            <div style={{ fontFamily:"'Syne',sans-serif", fontWeight:700, fontSize:14, marginBottom:12, color: byDay[day].length ? '#25D366' : '#7aab88' }}>
              {DAY_FR[day]}
              {byDay[day].length > 0 && <span style={{ ...S.tag, marginLeft:8, fontSize:10 }}>{byDay[day].length}</span>}
            </div>
            {byDay[day].length === 0 ? (
              <div style={{ fontSize:12, color:'#7aab88' }}>Fermé</div>
            ) : (
              byDay[day].map(r => (
                <div key={r.id} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8, background:'rgba(37,211,102,0.06)', border:'1px solid rgba(37,211,102,0.15)', borderRadius:8, padding:'6px 10px' }}>
                  <span style={{ fontSize:13, fontWeight:600 }}>{r.start_time} – {r.end_time}</span>
                  <button onClick={() => remove(r.id)} style={{ background:'none', border:'none', color:'#f87171', cursor:'pointer', fontSize:14, padding:0 }}>×</button>
                </div>
              ))
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── TAB: Paramètres ────────────────────────────────────────────────────── */
function SettingsTab() {
  const [config, setConfig] = useState(null);
  const [toast, setToast] = useState({ msg:'', type:'success' });

  useEffect(() => {
    api('/config').then(setConfig).catch(e => setToast({ msg:e.message, type:'error' }));
  }, []);

  const save = async () => {
    try {
      await api('/config', { method:'PUT', body:JSON.stringify(config) });
      setToast({ msg:'Configuration sauvegardée', type:'success' });
    } catch(e) { setToast({ msg:e.message, type:'error' }); }
  };

  if (!config) return <div style={{ textAlign:'center', padding:48, color:'#7aab88' }}>Chargement...</div>;

  return (
    <div>
      <Toast msg={toast.msg} type={toast.type} onClose={() => setToast({ msg:'' })} />
      <div style={{ ...S.card, maxWidth:600 }}>
        <div style={{ fontFamily:"'Syne',sans-serif", fontWeight:700, fontSize:16, marginBottom:20 }}>⚙️ Configuration Métier</div>
        <div style={{ display:'flex', flexDirection:'column', gap:18 }}>
          <div>
            <label style={S.label}>Type d'activité</label>
            <select style={S.select} value={config.business_type} onChange={e=>setConfig(c=>({...c,business_type:e.target.value}))}>
              <option value="ecommerce">🛒 E-commerce uniquement</option>
              <option value="appointments">🗓️ Rendez-vous uniquement</option>
              <option value="hybrid">⚡ Hybride (les deux)</option>
            </select>
            <div style={{ ...S.muted, marginTop:6 }}>
              {config.business_type === 'hybrid' && '⚡ Hybride : l\'IA gère à la fois les commandes et les RDV selon ce que demande le client.'}
              {config.business_type === 'appointments' && '🗓️ Tous les messages seront routés vers l\'agent de prise de RDV.'}
              {config.business_type === 'ecommerce' && '🛒 Mode e-commerce standard — aucun RDV géré par l\'IA.'}
            </div>
          </div>

          <div>
            <label style={S.label}>Catégorie de service</label>
            <select style={S.select} value={config.service_category || ''} onChange={e=>setConfig(c=>({...c,service_category:e.target.value||null}))}>
              <option value="">— Sélectionner —</option>
              <option value="medical">🏥 Médical</option>
              <option value="beauty">💅 Beauté / Coiffure</option>
              <option value="legal">⚖️ Juridique</option>
              <option value="fitness">💪 Sport / Fitness</option>
              <option value="restaurant">🍽️ Restaurant</option>
              <option value="auto">🚗 Automobile</option>
              <option value="other">📌 Autre</option>
            </select>
          </div>

          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
            <div>
              <label style={S.label}>Durée créneau par défaut (min)</label>
              <input type="number" style={S.input} value={config.default_slot_duration_min} onChange={e=>setConfig(c=>({...c,default_slot_duration_min:parseInt(e.target.value)}))} min={5} max={240}/>
            </div>
            <div>
              <label style={S.label}>Délai min avant réservation (h)</label>
              <input type="number" style={S.input} value={config.booking_lead_time_hours} onChange={e=>setConfig(c=>({...c,booking_lead_time_hours:parseInt(e.target.value)}))} min={0} max={72}/>
            </div>
          </div>

          <div>
            <label style={S.label}>Max RDV par jour</label>
            <input type="number" style={S.input} value={config.max_appointments_per_day || ''} onChange={e=>setConfig(c=>({...c,max_appointments_per_day:e.target.value?parseInt(e.target.value):null}))} placeholder="Illimité"/>
          </div>

          <div>
            <label style={S.label}>Adresse / Lieu</label>
            <input style={S.input} value={config.address || ''} onChange={e=>setConfig(c=>({...c,address:e.target.value}))} placeholder="Ex: 12 Rue de la République, Tunis"/>
          </div>

          <div>
            <label style={S.label}>Message de confirmation RDV</label>
            <textarea style={{...S.input,height:80,resize:'vertical'}} value={config.appointment_confirm_msg || ''} onChange={e=>setConfig(c=>({...c,appointment_confirm_msg:e.target.value}))} placeholder="Variables: {service}, {date}, {time}"/>
          </div>

          <div>
            <label style={S.label}>Message de rappel 24h avant</label>
            <textarea style={{...S.input,height:80,resize:'vertical'}} value={config.appointment_reminder_msg || ''} onChange={e=>setConfig(c=>({...c,appointment_reminder_msg:e.target.value}))} placeholder="Variables: {service}, {date}, {time}"/>
          </div>

          <button style={S.btnGreen} onClick={save}>💾 Sauvegarder la configuration</button>
        </div>
      </div>
    </div>
  );
}

/* ─── Main Page ──────────────────────────────────────────────────────────── */
// P1.2 FIX: tab name → index mapping for deep-link routing
const APPOINTMENTS_TAB_MAP = {
  agenda: 0, services: 1, availability: 2, settings: 3,
};

export default function Appointments({ initialTab = 'agenda' } = {}) {
  const { store } = useStore();
  const money = (value) => formatMoney(value, store, 'fr');
  const [activeTab, setActiveTab] = useState(APPOINTMENTS_TAB_MAP[initialTab] ?? 0);
  const [services, setServices] = useState([]);

  const loadServices = useCallback(async () => {
    try { setServices(await api('/services') || []); }
    catch { /* silently fail */ }
  }, []);

  useEffect(() => { loadServices(); }, [loadServices]);

  return (
    <div style={S.page}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500;600&display=swap');
        * { box-sizing: border-box; }
        input[type=number]::-webkit-inner-spin-button { opacity: 0.5; }
        input, select, textarea { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: #0a0f0d; }
        ::-webkit-scrollbar-thumb { background: #128C7E; border-radius: 2px; }
      `}</style>

      {/* Header */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:28, flexWrap:'wrap', gap:16 }}>
        <div>
          <h2 style={S.h2}>🗓️ Rendez-vous</h2>
          <p style={S.muted}>Gérez vos RDV, services et disponibilités</p>
        </div>
        <div style={{ display:'flex', gap:8, alignItems:'center' }}>
          <span style={{ ...S.tag, fontSize:12 }}>🤖 IA WhatsApp active</span>
          <span style={{ ...S.tag, fontSize:12, background:'rgba(96,165,250,0.1)', border:'1px solid rgba(96,165,250,0.2)', color:'#60a5fa' }}>🎙️ Vocal supporté</span>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display:'flex', gap:4, marginBottom:28, background:'#0d1910', borderRadius:12, padding:4, width:'fit-content', flexWrap:'wrap' }}>
        {TABS.map((tab, i) => (
          <button key={tab} onClick={() => setActiveTab(i)} style={{
            background: activeTab === i ? '#25D366' : 'transparent',
            color: activeTab === i ? '#000' : '#7aab88',
            border: 'none', borderRadius:9, padding:'9px 20px', fontSize:14,
            fontWeight: activeTab === i ? 700 : 500, cursor:'pointer',
            transition:'all 0.2s', fontFamily:"'DM Sans',sans-serif",
          }}>{tab}</button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 0 && <AgendaTab services={services} />}
      {activeTab === 1 && <ServicesTab services={services} reload={loadServices} />}
      {activeTab === 2 && <AvailabilityTab />}
      {activeTab === 3 && <SettingsTab />}
    </div>
  );
}
