// autocommerce-app/src/pages/VisualBuilder.jsx — Plan E1 page.
import React, { useState, useEffect } from "react";
import { api } from "../api";

const TABS = [
  { id: "description", label: "Description" },
  { id: "photos", label: "Photos" },
  { id: "seo", label: "SEO" },
  { id: "translations", label: "Traductions" },
  { id: "review", label: "Validation" },
  { id: "history", label: "Historique" },
];

export default function VisualBuilder() {
  const [tab, setTab] = useState("description");
  const [productName, setProductName] = useState("");
  const [tone, setTone] = useState("premium");
  const [build, setBuild] = useState(null);
  const [history, setHistory] = useState([]);
  const [seoKeywords, setSeoKeywords] = useState("durabilité, premium, made-in-france");
  const [locales, setLocales] = useState("en, es, de");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function generate() {
    setBusy(true); setError(null);
    try {
      const { data } = await api.post("/visual-builder/generate", {
        product_name: productName,
        tone,
      });
      setBuild(data);
      if (data?.id) await loadHistory(data.id);
    } catch (e) { setError(String(e?.message || e)); }
    finally { setBusy(false); }
  }

  async function loadHistory(id) {
    try {
      const { data } = await api.get(`/visual-builder/${id}/history`);
      setHistory(Array.isArray(data) ? data : []);
    } catch (e) { /* non-fatal */ }
  }

  async function generateSeo() {
    if (!build?.id) return;
    setBusy(true); setError(null);
    try {
      const kws = seoKeywords.split(",").map((s) => s.trim()).filter(Boolean);
      const { data } = await api.put(`/visual-builder/${build.id}/seo`, {
        target_locale: "fr", keywords: kws,
      });
      setBuild(data);
      await loadHistory(build.id);
    } catch (e) { setError(String(e?.message || e)); }
    finally { setBusy(false); }
  }

  async function translate() {
    if (!build?.id) return;
    setBusy(true); setError(null);
    try {
      const ls = locales.split(",").map((s) => s.trim()).filter(Boolean);
      const { data } = await api.put(`/visual-builder/${build.id}/translations`, {
        target_locales: ls,
        glossary: { "AutoCommerce": "AutoCommerce" },
      });
      setBuild(data);
      await loadHistory(build.id);
    } catch (e) { setError(String(e?.message || e)); }
    finally { setBusy(false); }
  }

  async function submitForReview() {
    if (!build?.id) return;
    setBusy(true);
    try {
      const { data } = await api.post(`/visual-builder/${build.id}/submit`, {});
      setBuild(data);
      await loadHistory(build.id);
    } catch (e) { setError(String(e?.message || e)); }
    finally { setBusy(false); }
  }

  async function review(decision) {
    if (!build?.id) return;
    setBusy(true);
    try {
      await api.post(`/visual-builder/${build.id}/review`, {
        decision, comments: decision === "approve" ? "OK" : "Voir notes",
      });
      const { data: refreshed } = await api.get("/visual-builder/");
      setBuild(Array.isArray(refreshed) ? refreshed.find((b) => b.id === build.id) : null);
      await loadHistory(build.id);
    } catch (e) { setError(String(e?.message || e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Visual Catalog Builder</h1>
        <span className="text-xs text-slate-500">
          {build ? `Build #${build.id} — ${build.status}` : "Aucun build"}
        </span>
      </header>

      <nav className="flex gap-2 border-b">
        {TABS.map((t) => (
          <button key={t.id}
            className={`px-3 py-2 text-sm border-b-2 ${
              tab === t.id ? "border-blue-600 text-blue-700" : "border-transparent text-slate-600"
            }`}
            onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {error && <div className="bg-red-50 text-red-700 p-2 rounded">{error}</div>}

      {tab === "description" && (
        <section className="space-y- omponent-block">
          <div className="grid grid-cols-2 gap-3">
            <input className="border rounded px-3 py-2"
              placeholder="Nom du produit"
              value={productName} onChange={(e) => setProductName(e.target.value)} />
            <select className="border rounded px-3 py-2"
              value={tone} onChange={(e) => setTone(e.target.value)}>
              <option value="premium">Premium</option>
              <option value="fun">Fun</option>
              <option value="technical">Technique</option>
              <option value="luxury">Luxe</option>
            </select>
          </div>
          <button disabled={busy || !productName}
            onClick={generate}
            className="px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-50">
            {busy ? "Génération…" : "Générer via IA"}
          </button>
          {build && (
            <div className="space-y-3 mt-4">
              <div><strong>Court :</strong> {build.description_short}</div>
              <div><strong>Long :</strong> <pre className="whitespace-pre-wrap text-sm">{build.description_long}</pre></div>
              <div>
                <strong>Bénéfices :</strong>
                <ul className="list-disc pl-6">
                  {(build.bullets || []).map((b, i) => <li key={i}>{b}</li>)}
                </ul>
              </div>
            </div>
          )}
        </section>
      )}

      {tab === "photos" && build && (
        <section className="space-y-3">
          <p className="text-sm text-slate-600">
            Uploadez ou collez des URLs d'images puis lancez l'amélioration IA (recadrage, alt-text, fond).
          </p>
          <button disabled={busy}
            className="px-4 py-2 bg-slate-700 text-white rounded"
            onClick={() => alert("Implémentez votre uploader ici (POST /visual-builder/{id}/photos)")}>
            Ajouter des photos
          </button>
        </section>
      )}

      {tab === "seo" && build && (
        <section className="space-y-3">
          <input className="border rounded px-3 py-2 w-full"
            value={seoKeywords} onChange={(e) => setSeoKeywords(e.target.value)}
            placeholder="mots-clés séparés par virgule" />
          <button disabled={busy} onClick={generateSeo}
            className="px-4 py-2 bg-emerald-600 text-white rounded">Optimiser SEO</button>
          {build.seo_title && (
            <div className="border rounded p-3 mt-3 space-y-2">
              <div className="text-blue-700 text-lg">{build.seo_title}</div>
              <div className="text-green-700 text-sm">{build.seo_meta}</div>
              <div className="text-xs">Score SEO : {build.seo_score}/100</div>
            </div>
          )}
        </section>
      )}

      {tab === "translations" && build && (
        <section className="space-y-3">
          <input className="border rounded px-3 py-2 w-full"
            value={locales} onChange={(e) => setLocales(e.target.value)}
            placeholder="locales séparés par virgule (en, es, de, it…)" />
          <button disabled={busy} onClick={translate}
            className="px-4 py-2 bg-indigo-600 text-white rounded">Traduire</button>
          {build.translations && Object.entries(build.translations).map(([loc, t]) => (
            <details key={loc} className="border rounded p-3 mt-2">
              <summary className="cursor-pointer font-semibold">{loc}</summary>
              <pre className="whitespace-pre-wrap text-sm">{JSON.stringify(t, null, 2)}</pre>
            </details>
          ))}
        </section>
      )}

      {tab === "review" && build && (
        <section className="space-y-3">
          <p className="text-sm">Statut : <strong>{build.status}</strong></p>
          <div className="flex gap-2">
            <button disabled={busy} onClick={submitForReview}
              className="px-4 py-2 bg-amber-600 text-white rounded">Soumettre à validation</button>
            <button disabled={busy} onClick={() => review("approve")}
              className="px-4 py-2 bg-emerald-600 text-white rounded">Approuver</button>
            <button disabled={busy} onClick={() => review("reject")}
              className="px-4 py-2 bg-red-600 text-white rounded">Rejeter</button>
            <button disabled={busy} onClick={() => review("changes_requested")}
              className="px-4 py-2 bg-yellow-600 text-white rounded">Demander des modifications</button>
          </div>
        </section>
      )}

      {tab === "history" && (
        <section className="space-y-2">
          <h3 className="font-semibold">Historique (audit immuable)</h3>
          {!build
            ? <p className="text-sm text-slate-500">Générez un build pour voir l'historique.</p>
            : history.length === 0
              ? <p className="text-sm text-slate-500">Aucun événement enregistré.</p>
              : <ul className="divide-y">
                  {history.map((h) => (
                    <li key={h.id} className="py-2">
                      <div className="text-xs text-slate-500">
                        {new Date(h.created_at).toLocaleString()} — {h.action}
                      </div>
                      {h.after && (
                        <pre className="text-xs bg-slate-50 rounded p-2 mt-1 overflow-x-auto">
                          {JSON.stringify(h.after, null, 2)}
                        </pre>
                      )}
                    </li>
                  ))}
                </ul>}
        </section>
      )}
    </div>
  );
}
