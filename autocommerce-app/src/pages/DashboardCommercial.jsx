/**
 * DashboardCommercial.jsx — Dashboard Commercial Enterprise (Phase 2)
 * KPIs : Leads Hot/Warm/Cold, Pipeline, Rappels, Opportunités
 */
import { useState, useEffect } from "react";
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from "recharts";
import api from "../api";
import { useStore } from "../context/StoreContext";
import { formatMoney } from "../utils/currency";

const LEAD_META = {
  hot:  { label: "Hot 🔥",  color: "#ef4444", bg: "bg-red-50",   text: "text-red-700",  border: "border-red-200" },
  warm: { label: "Warm 🌤",  color: "#f97316", bg: "bg-orange-50", text: "text-orange-700", border: "border-orange-200" },
  cold: { label: "Cold 🧊",  color: "#6366f1", bg: "bg-indigo-50", text: "text-indigo-700", border: "border-indigo-200" },
};

function LeadPill({ label, count, color, bg, text, border }) {
  return (
    <div className={`rounded-2xl ${bg} border ${border} p-5 flex flex-col gap-1`}>
      <div className={`text-sm font-medium ${text}`}>{label}</div>
      <div className={`text-4xl font-extrabold ${text}`}>{count}</div>
      <div className="text-xs text-gray-400">prospects</div>
    </div>
  );
}

export default function DashboardCommercial() {
  const [data, setData] = useState(null);
  const [period, setPeriod] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { store } = useStore();
  const money = (value) => formatMoney(value, store, 'fr');

  useEffect(() => {
    setLoading(true);
    api.get(`/dashboard-enterprise/commercial?period_days=${period}`)
      .then((r) => setData(r.data))
      .catch((e) => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  }, [period]);

  if (loading)
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-10 w-10 border-4 border-orange-500 border-t-transparent" />
      </div>
    );

  if (error)
    return <div className="p-6 bg-red-50 text-red-600 rounded-xl">Erreur : {error}</div>;

  const pieData = [
    { name: "Hot 🔥",  value: data?.leads?.hot  || 0, color: "#ef4444" },
    { name: "Warm 🌤", value: data?.leads?.warm || 0, color: "#f97316" },
    { name: "Cold 🧊", value: data?.leads?.cold || 0, color: "#6366f1" },
  ].filter((d) => d.value > 0);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-extrabold text-gray-900">Dashboard Commercial</h1>
          <p className="text-sm text-gray-400 mt-1">Pipeline Prospects & Opportunités</p>
        </div>
        <div className="flex gap-2">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setPeriod(d)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition ${
                period === d ? "bg-orange-500 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {d}j
            </button>
          ))}
        </div>
      </div>

      {/* Lead Score Pills */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        {["hot", "warm", "cold"].map((label) => (
          <LeadPill
            key={label}
            count={data?.leads?.[label] || 0}
            {...LEAD_META[label]}
          />
        ))}
      </div>

      {/* Pipeline + Rappels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        {/* Pipeline valeur */}
        <div className="premium-card p-6">
          <h2 className="text-lg font-bold text-gray-800 mb-4">Pipeline Estimé</h2>
          <div className="text-5xl font-extrabold text-indigo-600 mb-2">
            {money(data?.pipeline_value_tnd || 0)}
          </div>
          <p className="text-sm text-gray-400">
            Valeur estimée basée sur {data?.leads?.hot || 0} prospects chauds × commande moy.{" "}
            {money(data?.avg_order_value_tnd || 0)}
          </p>
          <div className="mt-4 flex gap-3">
            <div className="text-center flex-1 bg-gray-50 rounded-xl p-3">
              <div className="text-xl font-bold text-gray-800">{data?.opportunities || 0}</div>
              <div className="text-xs text-gray-400">Opportunités actives</div>
            </div>
            <div className="text-center flex-1 bg-amber-50 rounded-xl p-3">
              <div className="text-xl font-bold text-amber-600">{data?.recalls_suggested || 0}</div>
              <div className="text-xs text-gray-400">Rappels suggérés</div>
            </div>
          </div>
        </div>

        {/* Pie Chart distribution leads */}
        <div className="premium-card p-6">
          <h2 className="text-lg font-bold text-gray-800 mb-4">Répartition Prospects</h2>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" outerRadius={80} dataKey="value"
                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}>
                  {pieData.map((e, i) => <Cell key={i} fill={e.color} />)}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-40 text-gray-400 text-sm">
              Aucun prospect dans la période sélectionnée
            </div>
          )}
        </div>
      </div>

      {/* Actions suggérées */}
      <div className="bg-gradient-to-br from-indigo-50 to-purple-50 border border-indigo-200 rounded-2xl p-5">
        <h2 className="text-lg font-bold text-gray-800 mb-3">💡 Actions Suggérées</h2>
        <ul className="space-y-2 text-sm text-gray-600">
          {(data?.leads?.hot || 0) > 0 && (
            <li className="flex items-center gap-2">
              <span className="text-red-500">🔥</span>
              <strong>{data.leads.hot} prospects chauds</strong> — contacter en priorité avec une offre personnalisée
            </li>
          )}
          {(data?.recalls_suggested || 0) > 0 && (
            <li className="flex items-center gap-2">
              <span className="text-amber-500">📞</span>
              <strong>{data.recalls_suggested} rappels suggérés</strong> — clients actifs sans réponse récente
            </li>
          )}
          {(data?.opportunities || 0) > 0 && (
            <li className="flex items-center gap-2">
              <span className="text-indigo-500">🎯</span>
              <strong>{data.opportunities} opportunités</strong> — prospects chauds sans commande récente
            </li>
          )}
          {(data?.leads?.warm || 0) > 0 && (
            <li className="flex items-center gap-2">
              <span className="text-orange-400">🌤</span>
              <strong>{data.leads.warm} prospects tièdes</strong> — nurturer avec contenu et témoignages
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
