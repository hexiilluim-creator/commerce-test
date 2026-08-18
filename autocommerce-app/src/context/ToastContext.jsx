// src/context/ToastContext.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Système de toast global — remplace tous les alert() natifs du projet.
// • Mobile-first (bottom-center sur mobile, bottom-right sur desktop)
// • Auto-dismiss configurable (4.5s par défaut)
// • Branché sur api.ts → affiche automatiquement les erreurs API non gérées
// ─────────────────────────────────────────────────────────────────────────────
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import { setOnApiError } from '../api';

const ToastCtx = createContext(null);

let _id = 0;
const nextId = () => ++_id;

const TYPE_STYLES = {
  success: 'bg-green-600 text-white border-green-700',
  error: 'bg-red-600 text-white border-red-700',
  info: 'bg-gray-900 text-white border-gray-800',
  warning: 'bg-amber-500 text-white border-amber-600',
};

const TYPE_ICONS = {
  success: '✅',
  error: '⚠️',
  info: 'ℹ️',
  warning: '⚡',
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timersRef = useRef(new Map());

  const dismiss = useCallback((id) => {
    setToasts((list) => list.filter((t) => t.id !== id));
    const tm = timersRef.current.get(id);
    if (tm) {
      clearTimeout(tm);
      timersRef.current.delete(id);
    }
  }, []);

  const show = useCallback(
    (message, type = 'info', duration = 4500) => {
      if (!message) return;
      const id = nextId();
      setToasts((list) => [...list, { id, message: String(message), type }]);
      if (duration > 0) {
        const tm = setTimeout(() => dismiss(id), duration);
        timersRef.current.set(id, tm);
      }
      return id;
    },
    [dismiss]
  );

  const toast = {
    show,
    success: (m, d) => show(m, 'success', d),
    error: (m, d) => show(m, 'error', d ?? 5500),
    info: (m, d) => show(m, 'info', d),
    warning: (m, d) => show(m, 'warning', d),
    dismiss,
  };

  // ── Branche le handler erreur API global ──────────────────────────────────
  useEffect(() => {
    setOnApiError((message, status) => {
      // Messages utilisateurs simples
      let userMsg = message;
      if (status >= 500) userMsg = 'Erreur serveur, réessayer';
      else if (status === 404) userMsg = 'Ressource introuvable';
      else if (status === 403) userMsg = 'Accès refusé';
      else if (status === 422) userMsg = message || 'Données invalides';
      // On évite les détails techniques bruts (stack, traceback)
      if (userMsg && userMsg.length > 200) {
        userMsg = 'Erreur, réessayer';
      }
      show(userMsg || 'Erreur, réessayer', 'error');
    });
    return () => setOnApiError(null);
  }, [show]);

  // Cleanup
  useEffect(() => {
    return () => {
      timersRef.current.forEach((tm) => clearTimeout(tm));
      timersRef.current.clear();
    };
  }, []);

  return (
    <ToastCtx.Provider value={toast}>
      {children}
      <div
        aria-live="polite"
        className="fixed z-[9999] bottom-4 left-4 right-4 sm:left-auto sm:right-5 sm:bottom-5 sm:max-w-sm flex flex-col gap-2 pointer-events-none"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="alert"
            className={`pointer-events-auto flex items-start gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium animate-fade-in ${
              TYPE_STYLES[t.type] || TYPE_STYLES.info
            }`}
          >
            <span className="text-base leading-tight">
              {TYPE_ICONS[t.type] || 'ℹ️'}
            </span>
            <p className="flex-1 break-words">{t.message}</p>
            <button
              onClick={() => dismiss(t.id)}
              className="opacity-80 hover:opacity-100 text-lg leading-none -mt-0.5"
              aria-label="Fermer"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) {
    // Fallback no-op pour ne jamais crasher si utilisé hors provider
    return {
      show: () => {},
      success: () => {},
      error: () => {},
      info: () => {},
      warning: () => {},
      dismiss: () => {},
    };
  }
  return ctx;
}

export default ToastProvider;
