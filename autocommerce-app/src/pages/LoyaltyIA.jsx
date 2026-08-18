// autocommerce-app/src/pages/LoyaltyIA.jsx
//
// AUDIT FIX (retour utilisateur) : l'ancienne page était un outil de test
// technique (Model Registry, JSON brut, clients fictifs codés en dur).
// Remplacée par une vue simple : liste des vrais clients avec un statut
// clair (Fidèle / À relancer / Perdu) et un bouton d'action WhatsApp direct
// — pas de nouvelle table, pas d'envoi automatisé, juste un lien wa.me
// pré-rempli que le marchand envoie lui-même.
import React, { useEffect, useState } from "react";
import { api, extractErrorMessage } from "../api";
import { useStore } from "../context/StoreContext";
import { formatMoney } from "../utils/currency";

const STATUS_CONFIG = {
  fidele: {
    label: "Fidèle",
    color: "#16a34a",
    bg: "#f0fdf4",
    icon: "⭐",
    hint: "Client régulier — pensez à le remercier pour sa fidélité.",
  },
  a_relancer: {
    label: "À relancer",
    color: "#d97706",
    bg: "#fffbeb",
    icon: "⏰",
    hint: "N'a pas commandé récemment — une petite offre peut le faire revenir.",
  },
  perdu: {
    label: "Perdu",
    color: "#dc2626",
    bg: "#fef2f2",
    icon: "💤",
    hint: "Client inactif depuis longtemps — dernière chance de le relancer.",
  },
};

function buildWhatsAppLink(phone, name, status) {
  const messages = {
    fidele: `Bonjour ${name || ""} 👋 Merci pour votre fidélité ! En guise de remerciement, profitez d'une réduction spéciale sur votre prochaine commande 🎁`,
    a_relancer: `Bonjour ${name || ""} 👋 Ça fait un moment qu'on ne vous a pas vu ! Revenez faire un tour, on a une petite offre pour vous 😊`,
    perdu: `Bonjour ${name || ""} 👋 Vous nous manquez ! Profitez d'une offre spéciale pour votre retour 🎉`,
  };
  const text = encodeURIComponent(messages[status] || messages.a_relancer);
  const cleanPhone = (phone || "").replace(/[^0-9]/g, "");
  return `https://wa.me/${cleanPhone}?text=${text}`;
}

export default function LoyaltyIA() {
  const { store } = useStore();
  const money = (value) => formatMoney(value, store, 'fr');
  const [customers, setCustomers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    setLoading(true);
    api
      .get("/loyalty-ia/simple")
      .then(({ data }) => setCustomers(data.customers || []))
      .catch((e) => setError(extractErrorMessage(e)))
      .finally(() => setLoading(false));
  }, []);

  const filtered = filter === "all" ? customers : customers.filter((c) => c.status === filter);
  const counts = customers.reduce(
    (acc, c) => ({ ...acc, [c.status]: (acc[c.status] || 0) + 1 }),
    {}
  );

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "#94a3b8" }}>
        Chargement de vos clients…
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 24 }}>
        <div style={{ background: "#fef2f2", color: "#dc2626", padding: 16, borderRadius: 12 }}>
          {error}
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 4 }}>🎁 Fidélisation</h1>
      <p style={{ color: "#64748b", marginBottom: 24 }}>
        Voyez qui sont vos clients fidèles et lesquels ont besoin d'une petite
        attention pour revenir — envoyez-leur une offre en un clic.
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 24, flexWrap: "wrap" }}>
        <button
          onClick={() => setFilter("all")}
          style={{
            padding: "8px 16px", borderRadius: 20, border: "1px solid #e2e8f0",
            background: filter === "all" ? "#4f46e5" : "#fff",
            color: filter === "all" ? "#fff" : "#334155", fontWeight: 600, cursor: "pointer",
          }}
        >
          Tous ({customers.length})
        </button>
        {Object.entries(STATUS_CONFIG).map(([key, cfg]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            style={{
              padding: "8px 16px", borderRadius: 20, border: "1px solid #e2e8f0",
              background: filter === key ? cfg.color : "#fff",
              color: filter === key ? "#fff" : "#334155", fontWeight: 600, cursor: "pointer",
            }}
          >
            {cfg.icon} {cfg.label} ({counts[key] || 0})
          </button>
        ))}
      </div>

      {filtered.length === 0 && (
        <div style={{ padding: 40, textAlign: "center", color: "#94a3b8", background: "#f8fafc", borderRadius: 12 }}>
          {customers.length === 0
            ? "Pas encore assez de commandes pour analyser vos clients."
            : "Aucun client dans cette catégorie."}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {filtered.map((c) => {
          const cfg = STATUS_CONFIG[c.status];
          return (
            <div
              key={c.customer_id}
              style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: 16, borderRadius: 12, background: cfg.bg, border: `1px solid ${cfg.color}22`,
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <span style={{ fontWeight: 700 }}>{c.name}</span>
                  <span
                    style={{
                      fontSize: 12, fontWeight: 600, padding: "2px 8px", borderRadius: 10,
                      background: cfg.color, color: "#fff",
                    }}
                  >
                    {cfg.icon} {cfg.label}
                  </span>
                </div>
                <div style={{ fontSize: 13, color: "#64748b" }}>
                  {c.total_orders} commande{c.total_orders > 1 ? "s" : ""} ·{" "}
                  {money(c.total_spent)} dépensés · dernière commande il y a{" "}
                  {c.last_order_days_ago} jour{c.last_order_days_ago > 1 ? "s" : ""}
                </div>
              </div>
              <a
                href={buildWhatsAppLink(c.whatsapp_phone, c.name, c.status)}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "flex", alignItems: "center", gap: 6, padding: "10px 16px",
                  borderRadius: 8, background: "#25D366", color: "#fff", fontWeight: 600,
                  textDecoration: "none", fontSize: 14, whiteSpace: "nowrap",
                }}
              >
                📱 Envoyer une offre
              </a>
            </div>
          );
        })}
      </div>
    </div>
  );
}
