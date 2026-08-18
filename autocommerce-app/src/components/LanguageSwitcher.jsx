import { useTranslation } from 'react-i18next';
import { changeLanguage } from '../i18n/index.js';

/* ══════════════════════════════════════════════════════════════
   LanguageSwitcher — Sélecteur de langue avec drapeaux
   Supporte : Français 🇫🇷 | English 🇬🇧 | العربية 🇸🇦 | Deutsch 🇩🇪
══════════════════════════════════════════════════════════════ */

const LANGUAGES = [
  {
    code: 'fr',
    label: 'FR',
    fullLabel: 'Français',
    flag: (
      <svg width="20" height="15" viewBox="0 0 20 15" xmlns="http://www.w3.org/2000/svg" style={{ display: 'block' }}>
        <rect width="7" height="15" fill="#002395" />
        <rect x="7" width="6" height="15" fill="#FFFFFF" />
        <rect x="13" width="7" height="15" fill="#ED2939" />
      </svg>
    ),
  },
  {
    code: 'en',
    label: 'EN',
    fullLabel: 'English',
    flag: (
      <svg width="20" height="15" viewBox="0 0 60 40" xmlns="http://www.w3.org/2000/svg" style={{ display: 'block' }}>
        <rect width="60" height="40" fill="#012169" />
        <path d="M0,0 L60,40 M60,0 L0,40" stroke="#fff" strokeWidth="8" />
        <path d="M0,0 L60,40 M60,0 L0,40" stroke="#C8102E" strokeWidth="4" />
        <path d="M30,0 V40 M0,20 H60" stroke="#fff" strokeWidth="12" />
        <path d="M30,0 V40 M0,20 H60" stroke="#C8102E" strokeWidth="7" />
      </svg>
    ),
  },
  {
    code: 'ar',
    label: 'AR',
    fullLabel: 'العربية',
    flag: (
      <svg width="20" height="15" viewBox="0 0 20 15" xmlns="http://www.w3.org/2000/svg" style={{ display: 'block' }}>
        <rect width="20" height="5" fill="#006C35" />
        <rect y="5" width="20" height="5" fill="#FFFFFF" />
        <rect y="10" width="20" height="5" fill="#000000" />
      </svg>
    ),
  },
  {
    code: 'de',
    label: 'DE',
    fullLabel: 'Deutsch',
    flag: (
      <svg width="20" height="15" viewBox="0 0 20 15" xmlns="http://www.w3.org/2000/svg" style={{ display: 'block' }}>
        {/* Drapeau Allemagne : Noir / Rouge / Or */}
        <rect width="20" height="5" fill="#000000" />
        <rect y="5" width="20" height="5" fill="#DD0000" />
        <rect y="10" width="20" height="5" fill="#FFCE00" />
      </svg>
    ),
  },
];

export default function LanguageSwitcher({ variant = 'nav', className = '' }) {
  const { i18n } = useTranslation();
  const currentLang = i18n.language?.split('-')[0] || 'fr';

  const handleChange = (code) => {
    changeLanguage(code);
  };

  if (variant === 'compact') {
    return (
      <div className={`flex items-center gap-1 ${className}`} role="group" aria-label="Language selector">
        {LANGUAGES.map((lang) => (
          <button
            key={lang.code}
            onClick={() => handleChange(lang.code)}
            title={lang.fullLabel}
            aria-pressed={currentLang === lang.code}
            style={{
              border: currentLang === lang.code ? '2px solid #1D4ED8' : '2px solid transparent',
              borderRadius: '4px', padding: '2px', background: 'transparent', cursor: 'pointer',
              opacity: currentLang === lang.code ? 1 : 0.6, transition: 'all 0.2s',
              display: 'flex', alignItems: 'center',
            }}
          >
            {lang.flag}
          </button>
        ))}
      </div>
    );
  }

  if (variant === 'sidebar') {
    return (
      <div className={`flex items-center gap-1 px-3 py-2 ${className}`} role="group" aria-label="Language selector">
        <span className="text-[9px] font-bold text-gray-400 uppercase mr-1">Lang</span>
        {LANGUAGES.map((lang) => (
          <button
            key={lang.code}
            onClick={() => handleChange(lang.code)}
            title={lang.fullLabel}
            aria-pressed={currentLang === lang.code}
            style={{
              border: currentLang === lang.code ? '1.5px solid #1D4ED8' : '1.5px solid transparent',
              borderRadius: '4px', padding: '2px 4px',
              background: currentLang === lang.code ? '#EFF6FF' : 'transparent',
              cursor: 'pointer', transition: 'all 0.2s',
              display: 'flex', alignItems: 'center', gap: '3px',
            }}
          >
            {lang.flag}
            <span style={{ fontSize: '9px', fontWeight: 700, color: currentLang === lang.code ? '#1D4ED8' : '#6A6A6A' }}>
              {lang.label}
            </span>
          </button>
        ))}
      </div>
    );
  }

  // variant 'nav' (défaut)
  return (
    <div className={`flex items-center gap-1 ${className}`} role="group" aria-label="Language selector">
      {LANGUAGES.map((lang) => (
        <button
          key={lang.code}
          onClick={() => handleChange(lang.code)}
          title={lang.fullLabel}
          aria-pressed={currentLang === lang.code}
          style={{
            border: currentLang === lang.code ? '2px solid #1D4ED8' : '2px solid transparent',
            borderRadius: '6px', padding: '4px 8px',
            background: currentLang === lang.code ? '#EFF6FF' : 'transparent',
            cursor: 'pointer', transition: 'all 0.2s',
            display: 'flex', alignItems: 'center', gap: '5px',
            fontSize: '13px',
            fontWeight: currentLang === lang.code ? 700 : 500,
            color: currentLang === lang.code ? '#1D4ED8' : '#6A6A6A',
          }}
        >
          {lang.flag}
          <span>{lang.label}</span>
        </button>
      ))}
    </div>
  );
}
