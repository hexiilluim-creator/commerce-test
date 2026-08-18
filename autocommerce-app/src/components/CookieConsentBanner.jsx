/**
 * CookieConsentBanner.jsx — RGPD/GDPR Cookie Consent
 * Requis: ePrivacy Directive + RGPD Art. 6 (base légale consentement)
 * Marchés: UE, Tunisie (Loi 2004-63), Maroc (Loi 09-08), Algérie (Loi 18-07)
 */
import { useState, useEffect } from 'react';

const CONSENT_KEY = 'ac_cookie_consent_v1';

export function useCookieConsent() {
  const [consent, setConsent] = useState(null);
  useEffect(() => {
    try {
      const s = localStorage.getItem(CONSENT_KEY);
      if (s) setConsent(JSON.parse(s));
    } catch {}
  }, []);
  const save = (choices) => {
    const c = { necessary: true, analytics: false, marketing: false,
                ...choices, ts: new Date().toISOString() };
    localStorage.setItem(CONSENT_KEY, JSON.stringify(c));
    setConsent(c);
  };
  return { consent, save, hasConsented: consent !== null };
}

export default function CookieConsentBanner() {
  const { hasConsented, save } = useCookieConsent();
  const [expanded, setExpanded] = useState(false);
  const [analytics, setAnalytics] = useState(false);
  const [marketing, setMarketing] = useState(false);

  if (hasConsented) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 bg-white border-t border-gray-200 shadow-2xl">
      <div className="max-w-6xl mx-auto px-4 py-4">
        <div className="flex flex-col md:flex-row md:items-start gap-4">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-900 mb-1">
              🍪 Paramètres de confidentialité
            </p>
            <p className="text-xs text-gray-600 leading-relaxed">
              Nous utilisons des cookies essentiels pour le fonctionnement du service.
              Conformément au RGPD (Art. 6) et à la Directive ePrivacy, les cookies non
              essentiels nécessitent votre consentement.{' '}
              <button onClick={() => setExpanded(!expanded)}
                className="underline text-blue-600 hover:text-blue-800">
                {expanded ? 'Masquer' : 'Personnaliser'}
              </button>
              {' · '}
              <a href="/privacy" className="underline text-blue-600 hover:text-blue-800">
                Politique de confidentialité
              </a>
            </p>

            {expanded && (
              <div className="mt-3 space-y-2 p-3 bg-gray-50 rounded-lg">
                <label className="flex items-start gap-2 cursor-not-allowed">
                  <input type="checkbox" checked readOnly disabled className="mt-0.5 accent-gray-400" />
                  <span className="text-xs text-gray-700">
                    <strong>Nécessaires</strong> — authentification, session, sécurité CSRF
                    <span className="ml-1 text-gray-400">(obligatoires)</span>
                  </span>
                </label>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input type="checkbox" checked={analytics}
                    onChange={e => setAnalytics(e.target.checked)}
                    className="mt-0.5 accent-blue-600" />
                  <span className="text-xs text-gray-700">
                    <strong>Analytiques</strong> — métriques d'usage anonymisées (Prometheus)
                  </span>
                </label>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input type="checkbox" checked={marketing}
                    onChange={e => setMarketing(e.target.checked)}
                    className="mt-0.5 accent-blue-600" />
                  <span className="text-xs text-gray-700">
                    <strong>Marketing</strong> — personnalisation des offres et retargeting
                  </span>
                </label>
              </div>
            )}
          </div>

          <div className="flex flex-row sm:flex-col gap-2 shrink-0">
            <button onClick={() => save({ analytics: false, marketing: false })}
              className="flex-1 sm:flex-none px-4 py-2 text-xs border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors">
              Refuser tout
            </button>
            {expanded && (
              <button onClick={() => save({ analytics, marketing })}
                className="flex-1 sm:flex-none px-4 py-2 text-xs border border-blue-400 rounded-lg text-blue-700 hover:bg-blue-50 transition-colors">
                Enregistrer mes choix
              </button>
            )}
            <button onClick={() => save({ analytics: true, marketing: true })}
              className="flex-1 sm:flex-none px-4 py-2 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition-colors">
              Tout accepter
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
