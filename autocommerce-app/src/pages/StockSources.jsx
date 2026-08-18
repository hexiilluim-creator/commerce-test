import React, { useState, useEffect, useCallback } from 'react';
import axiosApi, { extractErrorMessage } from '../api';

/* API helper (compat) — utilise l'instance Axios centralisée */
const api = async (path, opts = {}) => {
  const method = (opts.method || 'GET').toUpperCase();
  let data = opts.body;
  if (typeof data === 'string') {
    try { data = JSON.parse(data); } catch { /* keep raw */ }
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

// Padding adaptatif : 14px sur mobile, 28px sur desktop (≥ 768px)
const _isMobile = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(max-width: 767px)').matches;
const S = {
  page:  { minHeight:'100vh', background:'#0a0f0d', color:'#e8f5ec', fontFamily:"'DM Sans',sans-serif", padding: _isMobile ? 14 : 28, overflowX: 'hidden' },
  card:  { background:'#141f18', border:'1px solid rgba(37,211,102,0.15)', borderRadius:16, padding: _isMobile ? 16 : 24 },
  input: { background:'#0d1910', border:'1px solid rgba(37,211,102,0.2)', borderRadius:10, padding:'10px 14px', color:'#e8f5ec', fontSize:14, width:'100%', outline:'none', boxSizing: 'border-box' },
  label: { fontSize:12, color:'#7aab88', marginBottom:6, display:'block', fontWeight:600 },
  btnG:  { background:'#25D366', color:'#000', border:'none', borderRadius:10, padding:'10px 22px', fontSize:14, fontWeight:700, cursor:'pointer' },
  btnO:  { background:'transparent', color:'#e8f5ec', border:'1px solid rgba(37,211,102,0.25)', borderRadius:10, padding:'10px 18px', fontSize:13, cursor:'pointer' },
  tag:   (ok) => ({ background: ok?'rgba(37,211,102,0.1)':'rgba(251,191,36,0.1)', border:`1px solid ${ok?'rgba(37,211,102,0.25)':'rgba(251,191,36,0.25)'}`, color:ok?'#25D366':'#fbbf24', borderRadius:100, padding:'3px 11px', fontSize:11, fontWeight:700 }),
  muted: { color:'#7aab88', fontSize:13 },
  h2:    { fontFamily:"'Syne',sans-serif", fontWeight:800, fontSize:20 },
  h3:    { fontFamily:"'Syne',sans-serif", fontWeight:700, fontSize:15 },
  sep:   { border:'none', borderTop:'1px solid rgba(37,211,102,0.1)', margin:'20px 0' },
};

function Toast({ msg, type, onClose }) {
  useEffect(() => { if(msg) { const t=setTimeout(onClose,3000); return ()=>clearTimeout(t); } }, [msg]);
  if (!msg) return null;
  return <div style={{ position:'fixed', bottom:24, right:24, zIndex:9999, background:type==='error'?'#2d0000':'#052e16', border:`1px solid ${type==='error'?'#7f1d1d':'#166534'}`, borderRadius:14, padding:'12px 20px', color:type==='error'?'#f87171':'#4ade80', fontWeight:600, fontSize:14 }}>{type==='error'?'❌ ':'✅ '}{msg}</div>;
}

// ─── Source configs ────────────────────────────────────────────────────────
const SOURCES = [
  { id:'dashboard',     label:'Dashboard AutoCommerce', icon:'🗂️', desc:'Produits saisis directement dans le dashboard. Aucune config requise.', fields:[] },
  { id:'google_sheets', label:'Google Sheets',          icon:'📊', desc:'Catalogue dans un Google Sheet publié en CSV. Sync automatique toutes les 15min.', fields:[
    { key:'sheet_url', label:'URL du Google Sheet', placeholder:'https://docs.google.com/spreadsheets/d/...', type:'url' },
  ]},
  { id:'woocommerce',   label:'WooCommerce',            icon:'🛒', desc:'Connecter votre boutique WooCommerce existante via REST API.', fields:[
    { key:'site_url',        label:'URL du site',         placeholder:'https://monsite.com', type:'url' },
    { key:'consumer_key',    label:'Consumer Key',        placeholder:'ck_xxxxxxxxxxxx', type:'text' },
    { key:'consumer_secret', label:'Consumer Secret',     placeholder:'cs_xxxxxxxxxxxx', type:'password' },
  ]},
  { id:'prestashop',    label:'PrestaShop',             icon:'🏪', desc:'Connecter votre boutique PrestaShop via API REST.', fields:[
    { key:'site_url', label:'URL du site',    placeholder:'https://monsite.com', type:'url' },
    { key:'api_key',  label:'Clé API',        placeholder:'ABCDEF1234567890...', type:'password' },
  ]},
  { id:'generic_api',   label:'API REST personnalisée', icon:'🔌', desc:'Toute API qui retourne un JSON avec les infos produit. Utiliser {query} ou {ref} dans l\'URL.', fields:[
    { key:'api_url', label:'URL de l\'API (avec {query})', placeholder:'https://mon-erp.com/api/pieces?q={query}', type:'url' },
  ]},
];

const OEM_APIS = [
  {
    id: 'tecdoc',
    label: 'TecDoc Web Services',
    icon: '🏆',
    badge: 'Payant — Précision maximale',
    badgeOk: false,
    desc: 'Standard mondial. 750M+ références OEM. Couvre tous les véhicules vendus en Europe et Afrique du Nord. ~500€/an.',
    link: 'https://www.tecalliance.net',
    fields: [
      { key:'tecdoc_api_key',    label:'Clé API TecDoc', placeholder:'Votre clé API TecDoc', type:'password' },
      { key:'tecdoc_provider_id', label:'Provider ID',   placeholder:'12345', type:'text' },
    ],
  },
  {
    id: 'autoiso',
    label: 'Auto-Iso API',
    icon: '🥈',
    badge: 'Payant — Alternative économique',
    badgeOk: false,
    desc: 'Alternative TecDoc moins chère. Bonne couverture Europe/Maghreb. Idéal pour démarrer sans engagement lourd.',
    link: 'https://api.auto-iso.fr',
    fields: [
      { key:'autoiso_api_key', label:'Clé API Auto-Iso', placeholder:'Votre clé API', type:'password' },
    ],
  },
  {
    id: 'nhtsa',
    label: 'NHTSA vPIC (VIN Decoder)',
    icon: '🆓',
    badge: 'Gratuit — Activé par défaut',
    badgeOk: true,
    desc: 'API officielle US Gov. Décode le VIN → Marque/Modèle/Année/Motorisation. 100% gratuit, sans clé. Base de 130+ attributs véhicule.',
    link: 'https://vpic.nhtsa.dot.gov/api/',
    fields: [],   // Aucun champ — toujours actif
  },
  {
    id: 'gpt',
    label: 'GPT-4o Estimation',
    icon: '🧠',
    badge: 'Inclus — Fallback IA',
    badgeOk: true,
    desc: 'Si aucune API OEM ne trouve la référence, l\'IA fait une estimation basée sur ses connaissances. Résultat marqué "à valider".',
    link: null,
    fields: [],
  },
];

// ─── Stock Source Section ─────────────────────────────────────────────────
function StockSourceSection({ storeData, onSave, toast }) {
  const [sourceType, setSourceType] = useState(storeData?.stock_source_type || 'dashboard');
  const [config, setConfig] = useState({});
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const selected = SOURCES.find(s => s.id === sourceType) || SOURCES[0];

  const handleSave = async () => {
    try {
      await api('/settings/stock-source', {
        method: 'PUT',
        body: JSON.stringify({ source_type: sourceType, config }),
      });
      onSave('Source de stock sauvegardée ✅');
    } catch(e) { toast(e.message, 'error'); }
  };

  const handleTest = async () => {
    setTesting(true); setTestResult(null);
    try {
      const r = await api('/settings/stock-source/test', {
        method: 'POST',
        body: JSON.stringify({ source_type: sourceType, config }),
      });
      setTestResult({ ok: r.ok, msg: r.message, count: r.count });
    } catch(e) { setTestResult({ ok: false, msg: e.message }); }
    finally { setTesting(false); }
  };

  return (
    <div style={S.card}>
      <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:20 }}>
        <div style={{ width:44, height:44, borderRadius:13, background:'rgba(37,211,102,0.1)', border:'1px solid rgba(37,211,102,0.2)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:22 }}>📦</div>
        <div><div style={S.h3}>Source du stock</div><div style={S.muted}>D'où l'IA récupère les données produits</div></div>
      </div>

      {/* Source selector */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(170px,1fr))', gap:10, marginBottom:24 }}>
        {SOURCES.map(s => (
          <div key={s.id} onClick={() => { setSourceType(s.id); setConfig({}); setTestResult(null); }}
            style={{ background: sourceType===s.id?'rgba(37,211,102,0.12)':'#0d1910', border:`1px solid ${sourceType===s.id?'rgba(37,211,102,0.5)':'rgba(37,211,102,0.1)'}`, borderRadius:12, padding:'12px 16px', cursor:'pointer', transition:'all 0.2s' }}>
            <div style={{ fontSize:22, marginBottom:6 }}>{s.icon}</div>
            <div style={{ fontSize:13, fontWeight:700, color: sourceType===s.id?'#25D366':'#e8f5ec' }}>{s.label}</div>
          </div>
        ))}
      </div>

      {/* Config fields */}
      <div style={{ background:'#0d1910', borderRadius:12, padding:20, marginBottom:16 }}>
        <div style={{ fontSize:13, color:'#7aab88', marginBottom:14 }}>{selected.desc}</div>
        {selected.fields.length === 0 ? (
          <div style={{ display:'flex', alignItems:'center', gap:8, color:'#25D366', fontSize:13, fontWeight:600 }}>
            <span>✅</span> Aucune configuration requise
          </div>
        ) : (
          <div style={{ display:'flex', flexDirection:'column', gap:14 }}>
            {selected.fields.map(f => (
              <div key={f.key}>
                <label style={S.label}>{f.label}</label>
                <input type={f.type} style={S.input} value={config[f.key]||''} onChange={e=>setConfig(c=>({...c,[f.key]:e.target.value}))} placeholder={f.placeholder}/>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Test result */}
      {testResult && (
        <div style={{ background: testResult.ok?'rgba(37,211,102,0.08)':'rgba(248,113,113,0.08)', border:`1px solid ${testResult.ok?'rgba(37,211,102,0.2)':'rgba(248,113,113,0.2)'}`, borderRadius:10, padding:'10px 16px', marginBottom:14, fontSize:13, color:testResult.ok?'#4ade80':'#f87171' }}>
          {testResult.ok ? `✅ Connexion OK — ${testResult.count||0} produit(s) trouvé(s)` : `❌ Erreur : ${testResult.msg}`}
        </div>
      )}

      <div style={{ display:'flex', gap:10 }}>
        <button style={S.btnG} onClick={handleSave}>💾 Enregistrer</button>
        {selected.fields.length > 0 && (
          <button style={S.btnO} onClick={handleTest} disabled={testing}>
            {testing ? '⏳ Test...' : '🔌 Tester la connexion'}
          </button>
        )}
      </div>
    </div>
  );
}

// ─── OEM APIs Section ─────────────────────────────────────────────────────
function OemApisSection({ storeData, toast }) {
  const [configs, setConfigs] = useState({
    tecdoc_api_key: '', tecdoc_provider_id: '', autoiso_api_key: '',
  });
  const [saved, setSaved] = useState({ tecdoc: false, autoiso: false });
  const [autoPartsMode, setAutoPartsMode] = useState(storeData?.auto_parts_mode || false);

  const saveOemKey = async (apiId) => {
    try {
      const payload = apiId === 'tecdoc'
        ? { tecdoc_api_key: configs.tecdoc_api_key, tecdoc_provider_id: configs.tecdoc_provider_id }
        : { autoiso_api_key: configs.autoiso_api_key };
      await api('/settings/oem-config', { method: 'PUT', body: JSON.stringify(payload) });
      setSaved(s => ({ ...s, [apiId]: true }));
      toast(`Clé ${apiId} enregistrée ✅`);
    } catch(e) { toast(e.message, 'error'); }
  };

  const saveAutoPartsMode = async (val) => {
    try {
      await api('/settings/store', { method: 'PATCH', body: JSON.stringify({ auto_parts_mode: val }) });
      setAutoPartsMode(val);
      toast(`Mode pièces auto ${val ? 'activé' : 'désactivé'} ✅`);
    } catch(e) { toast(e.message, 'error'); }
  };

  return (
    <div style={S.card}>
      <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:8 }}>
        <div style={{ width:44, height:44, borderRadius:13, background:'rgba(37,211,102,0.1)', border:'1px solid rgba(37,211,102,0.2)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:22 }}>🔍</div>
        <div><div style={S.h3}>APIs de références OEM</div><div style={S.muted}>Identification automatique des pièces par numéro constructeur</div></div>
      </div>

      {/* Auto parts mode toggle */}
      <div style={{ background:'rgba(37,211,102,0.06)', border:'1px solid rgba(37,211,102,0.2)', borderRadius:12, padding:16, marginBottom:24, display:'flex', alignItems:'center', justifyContent:'space-between', gap:16 }}>
        <div>
          <div style={{ fontWeight:700, fontSize:14, marginBottom:4 }}>🚗 Mode Pièces Auto</div>
          <div style={S.muted}>Active le workflow carte grise → pièce → stock pour toutes les conversations.</div>
        </div>
        <label style={{ display:'flex', alignItems:'center', gap:10, cursor:'pointer', flexShrink:0 }}>
          <div style={{ position:'relative', width:48, height:26 }} onClick={() => saveAutoPartsMode(!autoPartsMode)}>
            <div style={{ position:'absolute', inset:0, background:autoPartsMode?'#25D366':'#1a2e1e', borderRadius:13, transition:'background 0.2s' }}/>
            <div style={{ position:'absolute', top:3, left:autoPartsMode?22:3, width:20, height:20, background:'white', borderRadius:'50%', transition:'left 0.2s' }}/>
          </div>
          <span style={{ fontSize:13, fontWeight:700, color:autoPartsMode?'#25D366':'#7aab88' }}>{autoPartsMode ? 'Activé' : 'Désactivé'}</span>
        </label>
      </div>

      {/* Cascade explanation */}
      <div style={{ marginBottom:24 }}>
        <div style={{ fontSize:12, color:'#7aab88', fontWeight:700, letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:12 }}>Cascade de précision</div>
        <div style={{ display:'flex', flexDirection:'column', gap:3 }}>
          {['1. TecDoc (payant) → Précision maximale', '2. Auto-Iso (payant) → Alternative économique', '3. NHTSA vPIC (gratuit) → Décodage VIN', '4. GPT-4o (inclus) → Estimation fallback'].map((step, i) => (
            <div key={i} style={{ display:'flex', alignItems:'center', gap:10, padding:'8px 12px', background:'#0d1910', borderRadius:8 }}>
              <div style={{ width:24, height:24, borderRadius:'50%', background:`${i<2?'rgba(251,191,36,0.15)':'rgba(37,211,102,0.15)'}`, border:`1px solid ${i<2?'rgba(251,191,36,0.3)':'rgba(37,211,102,0.3)'}`, display:'flex', alignItems:'center', justifyContent:'center', fontSize:11, fontWeight:800, color:i<2?'#fbbf24':'#25D366', flexShrink:0 }}>{i+1}</div>
              <span style={{ fontSize:13, color:'#e8f5ec' }}>{step}</span>
            </div>
          ))}
        </div>
      </div>

      {/* API cards */}
      {OEM_APIS.map(api_def => (
        <div key={api_def.id} style={{ border:'1px solid rgba(37,211,102,0.12)', borderRadius:14, padding:20, marginBottom:16 }}>
          <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:12 }}>
            <span style={{ fontSize:24 }}>{api_def.icon}</span>
            <div style={{ flex:1 }}>
              <div style={{ fontWeight:700, fontSize:15, marginBottom:4, display:'flex', alignItems:'center', gap:8 }}>
                {api_def.label}
                <span style={S.tag(api_def.badgeOk)}>{api_def.badge}</span>
                {saved[api_def.id] && <span style={S.tag(true)}>✓ Configuré</span>}
              </div>
              <div style={{ fontSize:13, color:'#7aab88' }}>{api_def.desc}</div>
            </div>
            {api_def.link && (
              <a href={api_def.link} target="_blank" rel="noopener noreferrer" style={{ color:'#25D366', fontSize:12, textDecoration:'none', flexShrink:0, border:'1px solid rgba(37,211,102,0.2)', borderRadius:8, padding:'4px 10px' }}>
                🔗 Site →
              </a>
            )}
          </div>

          {api_def.fields.length > 0 && (
            <>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(200px,1fr))', gap:12, marginBottom:14 }}>
                {api_def.fields.map(f => (
                  <div key={f.key}>
                    <label style={S.label}>{f.label}</label>
                    <input type={f.type} style={S.input} value={configs[f.key]||''} onChange={e=>setConfigs(c=>({...c,[f.key]:e.target.value}))} placeholder={f.placeholder}/>
                  </div>
                ))}
              </div>
              <button style={{ ...S.btnG, fontSize:13, padding:'9px 20px' }} onClick={() => saveOemKey(api_def.id)}>
                💾 Enregistrer la clé
              </button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Workflow diagram ─────────────────────────────────────────────────────
function WorkflowDiagram() {
  const steps = [
    { icon:'📸', label:'Client envoie photo carte grise', color:'#60a5fa' },
    { icon:'🔍', label:'GPT-4o extrait le VIN + infos véhicule', color:'#a78bfa' },
    { icon:'🌐', label:'NHTSA vPIC décode le VIN (gratuit)', color:'#34d399' },
    { icon:'🏷️', label:'Lookup référence OEM (TecDoc / Auto-Iso / GPT)', color:'#fbbf24' },
    { icon:'📦', label:'Recherche dans votre stock (Sheets / WC / PS / Dashboard)', color:'#25D366' },
    { icon:'💬', label:'Réponse WhatsApp avec dispo et prix', color:'#25D366' },
  ];
  return (
    <div style={S.card}>
      <div style={{ ...S.h3, marginBottom:16 }}>🔄 Workflow Pièces Auto</div>
      <div style={{ display:'flex', flexDirection:'column', gap:0 }}>
        {steps.map((s, i) => (
          <div key={i} style={{ display:'flex', gap:14, alignItems:'flex-start' }}>
            <div style={{ display:'flex', flexDirection:'column', alignItems:'center' }}>
              <div style={{ width:40, height:40, borderRadius:'50%', background:`${s.color}15`, border:`1.5px solid ${s.color}40`, display:'flex', alignItems:'center', justifyContent:'center', fontSize:18, flexShrink:0 }}>{s.icon}</div>
              {i < steps.length-1 && <div style={{ width:2, height:24, background:'rgba(37,211,102,0.1)', margin:'3px 0' }}/>}
            </div>
            <div style={{ paddingTop:10, fontSize:14, color:'#e8f5ec', fontWeight: i===steps.length-1?700:400 }}>{s.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────
export default function StockSources() {
  const [storeData, setStoreData] = useState(null);
  const [toast, setToast] = useState({ msg:'', type:'success' });

  const showToast = (msg, type='success') => setToast({ msg, type });

  useEffect(() => {
    api('/settings/store').then(setStoreData).catch((e) => console.error('store load:', e));
  }, []);

  return (
    <div style={S.page}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:wght@400;500;600&display=swap');*{box-sizing:border-box}input,select,textarea{box-sizing:border-box}::-webkit-scrollbar{width:4px}::-webkit-scrollbar-thumb{background:#128C7E;border-radius:2px}`}</style>
      <Toast msg={toast.msg} type={toast.type} onClose={() => setToast({ msg:'' })} />

      {/* Header */}
      <div style={{ marginBottom:28 }}>
        <h1 style={{ ...S.h2, marginBottom:4 }}>🔌 Sources de données</h1>
        <p style={S.muted}>Configurez d'où l'IA récupère votre stock et les références OEM pièces auto.</p>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 340px', gap:20, alignItems:'start' }}>
        {/* Left — main config */}
        <div style={{ display:'flex', flexDirection:'column', gap:20 }}>
          <OemApisSection storeData={storeData} toast={showToast} />
          <StockSourceSection storeData={storeData} onSave={showToast} toast={showToast} />
        </div>

        {/* Right — workflow */}
        <div style={{ display:'flex', flexDirection:'column', gap:16, position:'sticky', top:24 }}>
          <WorkflowDiagram />

          {/* Quick tips */}
          <div style={S.card}>
            <div style={{ ...S.h3, marginBottom:12 }}>💡 Conseils</div>
            {[
              { icon:'📊', text:'Google Sheets : colonnes attendues — nom, reference, prix, stock, vehicules_compatibles' },
              { icon:'🆓', text:'Sans clé OEM, l\'IA estime la référence — résultats marqués "à valider"' },
              { icon:'🚗', text:'Le client peut envoyer la photo ou taper : "Renault Clio 2018 filtre huile"' },
              { icon:'🔑', text:'TecDoc = précision maximale, idéal si vous gérez 500+ références' },
            ].map(({ icon, text }, i) => (
              <div key={i} style={{ display:'flex', gap:10, marginBottom:12, alignItems:'flex-start' }}>
                <span style={{ fontSize:16, flexShrink:0 }}>{icon}</span>
                <span style={{ fontSize:13, color:'#7aab88', lineHeight:1.5 }}>{text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
