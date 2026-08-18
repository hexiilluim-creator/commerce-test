/**
 * DashboardIA.jsx — Dashboard IA Enterprise (Phase 2)
 * KPIs : conversations, satisfaction, émotions, escalades
 */
import { useState, useEffect } from "react";
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from "recharts";
import api from "../api";

const EMOTION_META = {
  neutral:    { label: "Neutre",     color: "#94a3b8", icon: "😐" },
  interested: { label: "Intéressé",  color: "#22d3ee", icon: "🤩" },
  hesitant:   { label: "Hésitant",   color: "#f59e0b", icon: "🤔" },
  frustrated: { label: "Frustré",    color: "#f97316", icon: "😤" },
  angry:      { label: "En colère",  color: "#ef4444", icon: "😡" },
  urgent:     { label: "Urgent",     color: "#8b5cf6", icon: "⚡" },
};

function MetricBlock({ label, value, sub, color }) {
  return (
    <div
      className="premium-card p-5"
      style={{ borderLeft: `4px solid ${color}` }}
    >
      <div className="text-sm text-gray-500 font-medium mb-1">{label}</div>
      <div className="text-3xl font-bold text-gray-800">{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  );
}

export default function DashboardIA() {
  const [data, setData] = useState(null);
  const [period, setPeriod] = useState(30);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    api.get(`/dashboard-enterprise/ai?period_days=${period}`)
      .then((r) => setData(r.data))
      .catch((e) => setError(e?.response?.data?.detail || e.message))
      .finally(() => setLoading(false));
  }, [period]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-10 w-10 border-4 border-cyan-500 border-t-transparent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 bg-red-50 rounded-xl text-red-600">Erreur : {error}</div>
    );
  }

  const emotionsChart = Object.entries(data?.emotions_distribution || {}).map(
    ([emotion, count]) => ({
      emotion: EMOTION_META[emotion]?.label || emotion,
      count,
      color: EMOTION_META[emotion]?.color || "#94a3b8",
      icon: EMOTION_META[emotion]?.icon || "❓",
    })
  );

  const satisfactionColor =
    (data?.satisfaction_score || 0) >= 80
      ? "#10b981"
      : (data?.satisfaction_score || 0) >= 60
      ? "#f59e0b"
      : "#ef4444";

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-extrabold text-gray-900">Dashboard IA</h1>
          <p className="text-sm text-gray-400 mt-1">Performance OmniCall — Intelligence Artificielle</p>
        </div>
        <div className="flex gap-2">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setPeriod(d)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition ${
                period === d ? "bg-cyan-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {d}j
            </button>
          ))}
        </div>
      </div>

      {/* KPI Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <MetricBlock
          label="Conversations"
          value={(data?.conversations?.total || 0).toLocaleString()}
          sub={`Résolutions : ${data?.conversations?.resolutions || 0}`}
          color="#6366f1"
        />
        <MetricBlock
          label="Taux de Résolution"
          value={`${data?.conversations?.resolution_rate_pct || 0}%`}
          color="#22d3ee"
        />
        <MetricBlock
          label="Score Satisfaction"
          value={`${data?.satisfaction_score || 0}%`}
          color={satisfactionColor}
        />
        <MetricBlock
          label="Escalades Humaines"
          value={(data?.human_handoffs?.total || 0).toLocaleString()}
          sub={`Résolues : ${data?.human_handoffs?.resolved || 0} | Moy. ${data?.human_handoffs?.avg_resolution_minutes || 0} min`}
          color="#f59e0b"
        />
      </div>

      {/* Satisfaction Score Gauge */}
      <div className="premium-card p-6 mb-6">
        <h2 className="text-lg font-bold text-gray-800 mb-4">Score de Satisfaction Client</h2>
        <div className="flex items-center gap-6">
          <div
            className="w-32 h-32 rounded-full flex items-center justify-center text-4xl font-extrabold text-white"
            style={{ background: `conic-gradient(${satisfactionColor} ${data?.satisfaction_score || 0}%, #e5e7eb 0)` }}
          >
            <div className="w-24 h-24 bg-white rounded-full flex items-center justify-center">
              <span style={{ color: satisfactionColor }} className="text-2xl font-bold">
                {data?.satisfaction_score || 0}%
              </span>
            </div>
          </div>
          <div>
            <p className="text-sm text-gray-500">
              Score basé sur l'absence d'émotions négatives (frustré, en colère)
              sur l'ensemble des clients du store.
            </p>
            <div className="mt-2 flex gap-2">
              {[
                { label: "Excellent", range: "≥ 80%", ok: (data?.satisfaction_score || 0) >= 80 },
                { label: "Bon", range: "60-79%", ok: (data?.satisfaction_score || 0) >= 60 },
                { label: "À améliorer", range: "< 60%", ok: (data?.satisfaction_score || 0) < 60 },
              ].map((s) => (
                <span
                  key={s.label}
                  className={`px-3 py-1 text-xs rounded-full font-medium ${
                    s.ok ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-400"
                  }`}
                >
                  {s.label} {s.range}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Distribution Émotions */}
      {emotionsChart.length > 0 && (
        <div className="premium-card p-6 mb-6">
          <h2 className="text-lg font-bold text-gray-800 mb-4">Distribution des Émotions Détectées</h2>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={emotionsChart} margin={{ top: 10, right: 20, bottom: 10, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="emotion" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip
                formatter={(v, n, p) => [v, `${p.payload.icon} ${n}`]}
              />
              <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                {emotionsChart.map((e, i) => (
                  <Cell key={i} fill={e.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Escalades Humaines Summary */}
      <div className="bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-200 rounded-2xl p-5">
        <h2 className="text-lg font-bold text-gray-800 mb-3">🙋 Escalades vers Agents Humains</h2>
        <div className="grid grid-cols-3 gap-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-orange-600">{data?.human_handoffs?.total || 0}</div>
            <div className="text-xs text-gray-500">Total escalades</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-green-600">{data?.human_handoffs?.resolved || 0}</div>
            <div className="text-xs text-gray-500">Résolues</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-blue-600">{data?.human_handoffs?.avg_resolution_minutes || 0} min</div>
            <div className="text-xs text-gray-500">Temps résolution moy.</div>
          </div>
        </div>
      </div>
    </div>
  );
}
