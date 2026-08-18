import { useEffect, useState } from 'react';

/**
 * Devise d'affichage de la landing et de la section pricing.
 *
 * Règle produit :
 *   - visiteur localisé en Tunisie (TN) : TND ;
 *   - tout autre pays : USD ;
 *   - géolocalisation indisponible : TND par défaut.
 *
 * Cette règle est uniquement cosmétique. Les prix de référence restent en TND
 * et le paiement réel est contrôlé côté backend.
 */
const CACHE_KEY = 'ac_geo_currency_v3';
const CACHE_TTL_MS = 30 * 60 * 1000;
const FETCH_TIMEOUT_MS = 4500;
const TND_TO_USD_RATE = 0.32;

const CURRENCY_META = {
  TND: { symbol: 'DT', rate: 1 },
  USD: { symbol: '$', rate: TND_TO_USD_RATE },
};

const GEO_PROVIDERS = [
  {
    url: 'https://ipapi.co/json/',
    readCountry: (data) => data?.country_code,
  },
  {
    url: 'https://ipwho.is/',
    readCountry: (data) => data?.country_code,
  },
];

export const DEFAULT_GEO_CURRENCY = {
  country: 'TN',
  currency: 'TND',
  symbol: CURRENCY_META.TND.symbol,
  rate: CURRENCY_META.TND.rate,
};

/** Retourne la devise selon le code pays ISO renvoyé par la géolocalisation IP. */
export function resolveLandingCurrency(countryCode) {
  const country = String(countryCode || '').trim().toUpperCase();
  const currency = country === 'TN' ? 'TND' : 'USD';
  return {
    country: country || 'TN',
    currency,
    symbol: CURRENCY_META[currency].symbol,
    rate: CURRENCY_META[currency].rate,
  };
}

function isValidCachedResult(value) {
  return Boolean(
    value &&
    (value.currency === 'TND' || value.currency === 'USD') &&
    typeof value.symbol === 'string' &&
    typeof value.rate === 'number' &&
    typeof value.savedAt === 'number' &&
    Date.now() - value.savedAt < CACHE_TTL_MS,
  );
}

function readCachedResult() {
  try {
    const cached = JSON.parse(sessionStorage.getItem(CACHE_KEY) || 'null');
    if (isValidCachedResult(cached)) {
      const { savedAt: _savedAt, ...result } = cached;
      return result;
    }
  } catch {
    // sessionStorage peut être bloqué en navigation privée.
  }
  return null;
}

function writeCachedResult(result) {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify({ ...result, savedAt: Date.now() }));
  } catch {
    // Le cache est facultatif : la détection réseau reste fonctionnelle.
  }
}

/**
 * Détecte le pays depuis l'IP publique avec un fournisseur de secours.
 * Retourne null si tous les fournisseurs sont indisponibles.
 */
export async function detectCountry() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    for (const provider of GEO_PROVIDERS) {
      try {
        const response = await fetch(provider.url, { signal: controller.signal });
        if (!response.ok) continue;
        const data = await response.json();
        const country = provider.readCountry(data);
        if (country) return country;
      } catch {
        if (controller.signal.aborted) break;
      }
    }
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

export function useGeoCurrency() {
  const [state, setState] = useState(() => {
    const cached = readCachedResult();
    return { ...(cached || DEFAULT_GEO_CURRENCY), loading: !cached };
  });

  useEffect(() => {
    let cancelled = false;
    if (readCachedResult()) return undefined;

    detectCountry()
      .then((countryCode) => {
        if (cancelled) return;
        const result = countryCode ? resolveLandingCurrency(countryCode) : DEFAULT_GEO_CURRENCY;
        setState({ ...result, loading: false });
        writeCachedResult(result);
      })
      .catch(() => {
        if (!cancelled) setState({ ...DEFAULT_GEO_CURRENCY, loading: false });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}

export default useGeoCurrency;
