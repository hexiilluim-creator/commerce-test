// autocommerce-app/src/pages/PredictiveRestocking.jsx — Plan E2 page.
import React, { useEffect, useState } from "react";
import { api } from "../api";

const SEVERITY_COLOR = {
  info: "bg-slate-200 text-slate-700",
  low: "bg-yellow-200 text-yellow-800",
  medium: "bg-orange-200 text-orange-900",
  high: "bg-red-200 text-red-900",
  critical: "bg-red-600 text-white",
};

export default function PredictiveRestocking() {
  const [sku, setSku] = useState("DEMO-001");
  const [horizon, setHorizon] = useState(14);
  const [alerts, setAlerts] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [forecast, setForecast] = useState(null);
  const [seasonality, setSeasonality] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function loadAll() {
    setBusy(true); setError(null);
    try {
      const [a, s] = await Promise.all([
        api.get("/restocking/alerts?limit=50"),
        api.get("/restocking/suggestions?limit=50"),
      ]);
      setAlerts(Array.isArray(a?.data) ? a.data : []);
      setSuggestions(Array.isArray(s?.data) ? s.data : []);
    } catch (e) { setError(String(e?.message || e)); }
    finally { setBusy(false); }
  }

  useEffect(() => { loadAll(); }, []);

  async function seedDemo() {
    setBusy(true); setError(null);
    try {
      const { data } = await api.post(`/restocking/seed-demo?sku=${encodeURIComponent(sku)}`, {});
      const f = await api.get(`/restocking/forecasts?sku=${encodeURIComponent(sku)}&horizon=${horizon}&limit=200`);
      const season = await api.post("/restocking/seasonality", {
        sku, horizon,
        history: [],
      });
      setForecast({ summary: data, raw: Array.isArray(f?.data) ? f.data : [] });
      setSeasonality(season?.data || null);
      await loadAll();
    } catch (e) { setError(String(e?.message || e)); }
    finally { setBusy(false); }
  }

  async function approveSuggestion(id) {
    setBusy(true);
    try {
      await api.post(`/restocking/${id}/approve`, { note: "OK" });
      await loadAll();
    } catch (e) { setError(String(e?.message || e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="p-6 space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Prédictif Restockage</h1>
        <div className="flex gap-2">
          <input className="border rounded px-3 py-1 text-sm"
            value={sku} onChange={(e) => setSku(e.target.value)} />
          <input className="border rounded px-3 py-1 text-sm w-20" type="number"
            value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} />
          <button onClick={seedDemo} disabled={busy}
            className="px-3 py-1 bg-blue-600 text-white text-sm rounded disabled:opacity-50">
            Lancer la démo
          </button>
        </div>
      </header>

      {error && <div className="bg-red-50 text-red-700 p-2 rounded">{error}</div>}

      <section className="grid md:grid-cols-2 gap-6">
        <div className="border rounded p-4">
          <h2 className="font-semibold mb-2">Alertes</h2>
          {alerts.length === 0
            ? <p className="text-sm text-slate-500">Aucune alerte active.</p>
            : <ul className="divide-y">
                {alerts.map((a) => (
                  <li key={a.id} className="py-2 flex items-center gap-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${SEVERITY_COLOR[a.severity] || "bg-slate-200"}`}>
                      {a.severity}
                    </span>
                    <div className="flex-1">
                      <div className="text-sm font-semibold">{a.sku} — {a.alert_type}</div>
                      <div className="text-xs text-slate-500">
                        Stock prédit : {a.predicted_stockout_date || "—"} · on_hand={a.on_hand}
                      </div>
                    </div>
                    <span className="text-xs">{a.status}</span>
                  </li>
                ))}
              </ul>}
        </div>

        <div className="border rounded p-4">
          <h2 className="font-semibold mb-2">Suggestions (validation humaine requise)</h2>
          {suggestions.length === 0
            ? <p className="text-sm text-slate-500">Aucune suggestion en attente.</p>
            : <ul className="divide-y">
                {suggestions.map((s) => (
                  <li key={s.id} className="py-2 flex items-start gap-3">
                    <div className="flex-1">
                      <div className="text-sm"><strong>{s.sku}</strong> — qty {Number(s.qty)} · lead {s.lead_time_days}j</div>
                      <div className="text-xs text-slate-500">{s.rationale}</div>
                      <div className="text-xs">Statut : {s.status}</div>
                    </div>
                    {s.status === "pending" && (
                      <button onClick={() => approveSuggestion(s.id)}
                        className="text-xs px-2 py-1 bg-emerald-600 text-white rounded">
                        Approuver
                      </button>
                    )}
                  </li>
                ))}
              </ul>}
        </div>
      </section>

      {forecast && (
        <section className="border rounded p-4">
          <h2 className="font-semibold mb-2">Forecast démo — {forecast.summary?.sku}</h2>
          <p className="text-sm text-slate-700">
            Première prévision : <strong>{Number(forecast.summary?.forecast_first || 0).toFixed(2)}</strong>
            {" "}pour horizon {horizon}j. Lignes brutes : {forecast.raw.length}.
          </p>
        </section>
      )}

      {seasonality && (
        <section className="border rounded p-4">
          <h2 className="font-semibold mb-2">Saisonnalité</h2>
          {seasonality.weekly_profile && (
            <Sparkline data={Object.values(seasonality.weekly_profile)} />
          )}
          <div className="text-xs text-slate-500">
            Trend slope : {seasonality.trend_slope?.toFixed?.(4) || seasonality.trend_slope}{" "}
            · Residual std : {seasonality.residual_std?.toFixed?.(4) || seasonality.residual_std}
          </div>
        </section>
      )}
    </div>
  );
}

function Sparkline({ data }) {
  if (!Array.isArray(data) || data.length === 0) return null;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const span = Math.max(1e-6, max - min);
  return (
    <svg viewBox={`0 0 ${data.length * 10} 40`} className="w-full h-12">
      {data.map((v, i) => {
        const x = i * 10;
        const y = 40 - ((v - min) / span) * 36;
        return <circle key={i} cx={x + 5} cy={y} r="2.5" fill="#2563eb" />;
      })}
      <polyline
        fill="none" stroke="#2563eb" strokeWidth="1.5"
        points={data.map((v, i) => {
          const x = i * 10 + 5;
          const y = 40 - ((v - min) / span) * 36;
          return `${x},${y}`;
        }).join(" ")}
      />
    </svg>
  );
}
