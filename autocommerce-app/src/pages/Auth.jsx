import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../context/StoreContext';
import { useTranslation } from 'react-i18next';
import LanguageSwitcher from '../components/LanguageSwitcher';
// P0-FIX (audit): use the central Axios client so the CSRF token, baseURL,
// withCredentials and the global error handler are applied uniformly.
import { apiPost, extractErrorMessage } from '../api';

// P0-FIX (audit): the backend currently returns 501 on /auth/google-login.
// The button is hidden by default and can be re-enabled by env var when
// real OAuth verification is wired (see backend/api/v1/auth.py::google_login).
const GOOGLE_LOGIN_ENABLED =
  ((import.meta).env?.VITE_GOOGLE_LOGIN_ENABLED ?? 'false') === 'true';

export default function Auth() {
  const { login, register, loading, error } = useStore();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const isRTL = i18n.language === 'ar';
  
  const [mode, setMode] = useState('login'); // 'login' | 'register' | 'forgot'
  const [showPassword, setShowPassword] = useState(false);
  const [form, setForm] = useState({ 
    email: '', 
    password: '', 
    confirmPassword: '', 
    storeName: '' 
  });
  const [message, setMessage] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage('');

    // Validation basique
    if (form.email && !form.email.includes('@')) {
      alert("Veuillez entrer une adresse email valide");
      return;
    }

    if (mode !== 'forgot' && form.password.length < 6) {
      alert("Le mot de passe doit contenir au moins 6 caractères");
      return;
    }
    
    if (mode === 'forgot') {
      try {
        // P0-FIX (audit): go through the central Axios client so the CSRF
        // token cookie is honoured automatically and the global 401/error
        // handling stays consistent. The previous direct fetch() bypassed
        // all of that and broke the contract with the backend middleware.
        const data = await apiPost('/auth/forgot-password', { email: form.email });
        setMessage(data.message || 'Si l\u2019email existe, un lien a \u00e9t\u00e9 envoy\u00e9.');
      } catch (err) {
        setMessage(extractErrorMessage(err));
      }
      return;
    }

    let ok;
    if (mode === 'login') {
      ok = await login(form.email, form.password);
    } else {
      if (form.password !== form.confirmPassword) {
        alert("Les mots de passe ne correspondent pas");
        return;
      }
      ok = await register(form.email, form.password, form.storeName, form.confirmPassword);
    }
    if (ok) navigate('/dashboard');
  };

  const handleGoogleLogin = () => {
    // P0-FIX (audit): backend returns 501 — do not pretend the feature exists.
    setMessage('Google login is not available yet. Use email/password.');
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#101828] p-4 sm:p-6" dir={isRTL ? 'rtl' : 'ltr'}>
      <div className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-[#635bff]/30 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-32 -right-20 h-96 w-96 rounded-full bg-[#c6923e]/20 blur-3xl" />
      <div className="relative w-full max-w-md rounded-[28px] border border-white/10 bg-white p-6 shadow-[0_32px_90px_rgba(0,0,0,.35)] sm:p-9">
        <div className="flex justify-end mb-4">
          <LanguageSwitcher variant="compact" />
        </div>

        <div className="text-center mb-8">
          <div className="mx-auto mb-4 grid h-16 w-16 place-items-center rounded-[22px] bg-gradient-to-br from-[#8177ff] via-[#635bff] to-[#4f46e5] text-lg font-black tracking-tight text-white shadow-[0_14px_28px_rgba(99,91,255,.28)]">
            AC
          </div>
          <h1 className="text-2xl font-bold text-gray-900">
            {mode === 'forgot' ? 'Mot de passe oublié' : t('auth.title')}
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            {mode === 'forgot' ? 'Entrez votre email pour réinitialiser' : t('auth.subtitle')}
          </p>
        </div>

        {mode !== 'forgot' && (
          <div className="flex mb-6 bg-gray-100 rounded-xl p-1">
            {['login', 'register'].map((m) => (
              <button
                key={m}
                onClick={() => { setMode(m); setMessage(''); }}
                className={`flex-1 py-2.5 rounded-xl text-sm font-bold transition-all ${
                  mode === m ? 'bg-white shadow text-indigo-600' : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {m === 'login' ? t('auth.login') : t('auth.register')}
              </button>
            ))}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === 'register' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth.storeName')}</label>
              <input
                type="text" required
                value={form.storeName}
                onChange={(e) => setForm({ ...form, storeName: e.target.value })}
                className="input-premium"
                placeholder={t('auth.storeNamePlaceholder')}
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth.email')}</label>
            <input
              type="email" required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              className="input-premium"
              placeholder={t('auth.emailPlaceholder')}
              dir="ltr"
            />
          </div>

          {mode !== 'forgot' && (
            <>
              <div className="relative">
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('auth.password')}</label>
                <input
                  type={showPassword ? "text" : "password"} required
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  className="input-premium"
                  placeholder={t('auth.passwordPlaceholder')}
                  dir="ltr"
                />
                <button 
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-9 text-gray-400 hover:text-gray-600 focus:outline-none"
                  title={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
                >
                  {showPassword ? '👁️' : '🙈'}
                </button>
              </div>

              {mode === 'register' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Confirmer le mot de passe</label>
                  <input
                    type="password" required
                    value={form.confirmPassword}
                    onChange={(e) => setForm({ ...form, confirmPassword: e.target.value })}
                    className="input-premium"
                    placeholder="Répétez votre mot de passe"
                    dir="ltr"
                  />
                </div>
              )}
            </>
          )}

          {mode === 'login' && (
            <div className="text-right">
              <button 
                type="button"
                onClick={() => setMode('forgot')}
                className="text-sm text-indigo-600 hover:underline"
              >
                Mot de passe oublié ?
              </button>
            </div>
          )}

          {error && <div className="text-red-600 text-sm bg-red-50 p-2 rounded-lg">{error}</div>}
          {message && <div className="text-green-600 text-sm bg-green-50 p-2 rounded-lg">{message}</div>}

          <button
            type="submit" disabled={loading}
            className={`button-primary w-full ${
              loading 
                ? 'cursor-not-allowed bg-[#a9a5ff] text-white/70' 
                : ''
            }`}
          >
            {loading && (
              <svg className="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            )}
            <span>
              {loading 
                ? t('auth.loading') 
                : mode === 'login' 
                  ? t('auth.loginBtn') 
                  : mode === 'register' 
                    ? t('auth.registerBtn') 
                    : 'Envoyer le lien'}
            </span>
          </button>

          {mode === 'forgot' && (
            <button 
              type="button"
              onClick={() => setMode('login')}
              className="w-full text-sm text-gray-500 hover:underline mt-2"
            >
              Retour à la connexion
            </button>
          )}
        </form>

        {/* P0-FIX (audit): Google login is hidden until the backend
            implements real OAuth verification. Toggle with
            VITE_GOOGLE_LOGIN_ENABLED=true when ready. */}
        {mode !== 'forgot' && GOOGLE_LOGIN_ENABLED && (
          <>
            <div className="relative my-6">
              <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-gray-200"></div></div>
              <div className="relative flex justify-center text-sm"><span className="px-2 bg-white text-gray-500">Ou continuer avec</span></div>
            </div>

            <button
              type="button"
              onClick={handleGoogleLogin}
              className="w-full flex items-center justify-center gap-3 px-4 py-2.5 border border-gray-300 rounded-xl hover:bg-gray-50 transition-colors font-medium text-gray-700"
            >
              <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="Google" className="w-5 h-5" />
              Google
            </button>
          </>
        )}
      </div>
    </div>
  );
}
