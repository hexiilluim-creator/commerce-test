const FALLBACKS = {
  TN: { currency: 'TND', locale: 'fr-TN', decimals: 3 },
  FR: { currency: 'EUR', locale: 'fr-FR', decimals: 2 },
  US: { currency: 'USD', locale: 'en-US', decimals: 2 },
  DE: { currency: 'EUR', locale: 'de-DE', decimals: 2 },
  GB: { currency: 'GBP', locale: 'en-GB', decimals: 2 },
  MA: { currency: 'MAD', locale: 'fr-MA', decimals: 2 },
  DZ: { currency: 'DZD', locale: 'fr-DZ', decimals: 2 },
  SA: { currency: 'SAR', locale: 'ar-SA', decimals: 2 },
  AE: { currency: 'AED', locale: 'ar-AE', decimals: 2 },
  CA: { currency: 'CAD', locale: 'fr-CA', decimals: 2 },
};

const LANGUAGE_LOCALES = {
  fr: 'fr-FR',
  en: 'en-US',
  ar: 'ar-SA',
  de: 'de-DE',
};

export function getCurrencyConfig(store = {}, language = 'fr') {
  const country = String(store?.country || 'TN').toUpperCase();
  const fallback = FALLBACKS[country] || FALLBACKS.TN;
  const currency = store?.currency || fallback.currency;
  const locale = store?.locale || LANGUAGE_LOCALES[String(language).split('-')[0]] || fallback.locale;
  const decimals = currency === 'TND' || currency === 'KWD' || currency === 'BHD' ? 3 : 2;
  return { country, currency, locale, decimals };
}

export function formatMoney(amount, store = {}, language = 'fr') {
  const { currency, locale, decimals } = getCurrencyConfig(store, language);
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(Number(amount || 0));
}

export function currencyLabel(store = {}, language = 'fr') {
  return getCurrencyConfig(store, language).currency;
}

export { FALLBACKS };
