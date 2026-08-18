import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import fr from './fr.json';
import en from './en.json';
import ar from './ar.json';
import de from './de.json';

const STORAGE_KEY = 'autocommerce_lang';
const SUPPORTED_LANGS = ['fr', 'en', 'ar', 'de'];

function detectInitialLanguage() {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && SUPPORTED_LANGS.includes(stored)) return stored;

  const browserLang = navigator.language?.split('-')[0]?.toLowerCase();
  if (SUPPORTED_LANGS.includes(browserLang)) return browserLang;

  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    // Détection Allemagne/Autriche/Suisse → Allemand
    if (['Europe/Berlin','Europe/Vienna','Europe/Zurich','Europe/Busingen'].includes(tz)) {
      return 'de';
    }
    if (tz.startsWith('Africa/') || tz.startsWith('Asia/')) {
      const arabicTz = [
        'Africa/Cairo','Africa/Algiers','Africa/Tunis','Africa/Tripoli',
        'Africa/Casablanca','Africa/Nouakchott','Asia/Riyadh','Asia/Dubai',
        'Asia/Baghdad','Asia/Beirut','Asia/Amman','Asia/Damascus',
        'Asia/Kuwait','Asia/Qatar','Asia/Bahrain','Asia/Muscat',
        'Asia/Aden','Africa/Khartoum','Africa/Mogadishu',
      ];
      if (arabicTz.includes(tz)) return 'ar';
    }
  } catch (_) { /* ignore */ }

  return 'fr';
}

const initialLang = detectInitialLanguage();

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      fr: { translation: fr },
      en: { translation: en },
      ar: { translation: ar },
      de: { translation: de },
    },
    lng: initialLang,
    fallbackLng: 'fr',
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: STORAGE_KEY,
    },
  });

export function changeLanguage(lang) {
  if (!SUPPORTED_LANGS.includes(lang)) return;
  localStorage.setItem(STORAGE_KEY, lang);
  i18n.changeLanguage(lang);
  applyDocumentDirection(lang);
}

export function applyDocumentDirection(lang) {
  const dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.documentElement.dir = dir;
  document.documentElement.lang = lang;
  document.body.dir = dir;
}

applyDocumentDirection(initialLang);

export default i18n;
