// src/api.ts
// ─────────────────────────────────────────────────────────────────────────────
// Instance Axios centralisée — UNIQUE point d'entrée pour les appels backend.
// • baseURL = /api/v1 (configurable via VITE_API_URL)
// • withCredentials = true → cookies HttpOnly envoyés automatiquement
// • Intercepteur CSRF → attach X-CSRF-Token sur toutes les requêtes mutantes
// • Intercepteur 401 → tente un refresh silencieux une seule fois, met en file
//   d'attente les requêtes concurrentes pendant le refresh, puis réessaie.
//   Si le refresh échoue → déclenche le hook global onUnauthorized (logout+redirect)
// • Intercepteur d'erreur → normalise les messages pour le toast global
// ─────────────────────────────────────────────────────────────────────────────
import axios, {
  AxiosError,
  AxiosInstance,
  AxiosRequestConfig,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from 'axios';

// CTO audit fix: removed 'as any' and 'as unknown' casts for robust types.
// We use a safe check for import.meta.env which is standard in Vite.
// P0-FIX: Assure-toi que VITE_API_URL est utilisé correctement avec un fallback robuste
const rawApiUrl = import.meta.env?.VITE_API_URL as string;
const BASE_URL: string = rawApiUrl ? (rawApiUrl.endsWith('/api/v1') ? rawApiUrl : `${rawApiUrl}/api/v1`.replace(/\/+/g, '/').replace(':/', '://')) : '/api/v1';

const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
  headers: {
    Accept: 'application/json',
  },
  timeout: 30000,
});

// ─── Hook 401 : permet à StoreContext (ou autre) de réagir à une expiration ──
type UnauthorizedHandler = () => void;
let onUnauthorizedHandler: UnauthorizedHandler | null = null;

export function setOnUnauthorized(handler: UnauthorizedHandler | null): void {
  onUnauthorizedHandler = handler;
}

// ─── Hook erreur globale (pour le toast) ────────────────────────────────────
type ErrorHandler = (message: string, status?: number) => void;
let onApiErrorHandler: ErrorHandler | null = null;

export function setOnApiError(handler: ErrorHandler | null): void {
  onApiErrorHandler = handler;
}

interface ApiErrorData {
  detail?: string;
  error?: string;
  message?: string;
}

// ─── Helpers d'extraction de message d'erreur ───────────────────────────────
export function extractErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const ax = err as AxiosError<ApiErrorData>;
    const data = ax.response?.data;
    if (data) {
      if (typeof data === 'string') return data;
      if (data.detail && typeof data.detail === 'string') return data.detail;
      if (data.error && typeof data.error === 'string') return data.error;
      if (data.message && typeof data.message === 'string') return data.message;
    }
    if (ax.code === 'ECONNABORTED') return 'Délai dépassé, le serveur ne répond pas. Réessayez.';
    if (ax.message === 'Network Error') return 'Erreur Réseau : Impossible de contacter le serveur (CORS ou Connexion).';
    if (ax.message) return ax.message;
  }
  if (err instanceof Error) return err.message;
  return 'Une erreur inattendue est survenue. Veuillez réessayer.';
}

// ─── Routes d'authentification à ne jamais retenter après un 401 ─────────────
const AUTH_ROUTES = ['/auth/login', '/auth/refresh', '/auth/logout', '/auth/register'];

function isAuthRoute(url: string | undefined): boolean {
  if (!url) return false;
  return AUTH_ROUTES.some((r) => url.includes(r));
}

// ─── État du refresh silencieux ───────────────────────────────────────────────
// isRefreshing  : un refresh est déjà en cours, ne pas en lancer un second
// pendingQueue  : requêtes en attente de la fin du refresh
let isRefreshing = false;
type QueueItem = { resolve: (value: unknown) => void; reject: (reason?: unknown) => void };
let pendingQueue: QueueItem[] = [];

function flushQueue(error: unknown, token: unknown = null): void {
  pendingQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error);
    else resolve(token);
  });
  pendingQueue = [];
}

// Appel effectif à /auth/refresh — retourne true si succès, false sinon
async function doRefresh(): Promise<boolean> {
  try {
    await axios.post(
      `${BASE_URL}/auth/refresh`,
      {},
      { withCredentials: true, timeout: 10000 }
    );
    return true;
  } catch {
    return false;
  }
}

function fireUnauthorized(): void {
  if (onUnauthorizedHandler) {
    try {
      onUnauthorizedHandler();
    } catch {
      /* noop */
    }
  } else if (
    typeof window !== 'undefined' &&
    window.location.pathname !== '/login' &&
    window.location.pathname !== '/' &&
    !window.location.pathname.startsWith('/boutique/')
  ) {
    window.location.href = '/login';
  }
}

// ─── Intercepteur de requête — CSRF ──────────────────────────────────────────
// P0-3 FIX: attach le csrf_token (cookie non-HttpOnly) sur toutes les mutations.
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const method = (config.method || '').toUpperCase();
  const MUTATING = ['POST', 'PUT', 'PATCH', 'DELETE'];
  if (MUTATING.includes(method)) {
    if (typeof document === 'undefined') return config; // SSR safety
    const csrfToken = document.cookie
      .split(';')
      .map((c) => c.trim())
      .find((c) => c.startsWith('csrf_token='))
      ?.split('=')[1];
    if (csrfToken) {
      config.headers = config.headers ?? {};
      (config.headers as Record<string, string>)['X-CSRF-Token'] = decodeURIComponent(csrfToken);
    }
  }
  return config;
});

// ─── Intercepteur de réponse — Refresh silencieux sur 401 ───────────────────
api.interceptors.response.use(
  (res: AxiosResponse) => res,
  async (err: AxiosError & { config?: AxiosRequestConfig & { _retry?: boolean } }) => {
    const status = err.response?.status;
    const originalConfig = err.config;

    // Tente un refresh silencieux uniquement si :
    //   - status 401 ET
    //   - ce n'est pas une route d'auth (évite boucle infinie) ET
    //   - ce n'est pas déjà une tentative de retry
    if (status === 401 && originalConfig && !isAuthRoute(originalConfig.url) && !originalConfig._retry) {
      if (isRefreshing) {
        // Un refresh est déjà en cours → mettre en file d'attente
        return new Promise((resolve, reject) => {
          pendingQueue.push({ resolve, reject });
        }).then(() => api(originalConfig));
      }

      originalConfig._retry = true;
      isRefreshing = true;

      const refreshed = await doRefresh();

      isRefreshing = false;

      if (refreshed) {
        flushQueue(null, true);
        return api(originalConfig);
      } else {
        flushQueue(new Error('Session expirée'), null);
        fireUnauthorized();
        return Promise.reject(err);
      }
    }

    // 401 sur une route d'auth (login/refresh échoué) → logout direct
    if (status === 401 && isAuthRoute(originalConfig?.url)) {
      fireUnauthorized();
    }

    // Notification globale (sauf 401 déjà géré + sauf /auth/me silencieux)
    const url = (originalConfig?.url || '') as string;
    const isAuthMeProbe = url.includes('/auth/me');
    if (!isAuthMeProbe && status !== 401 && onApiErrorHandler) {
      try {
        onApiErrorHandler(extractErrorMessage(err), status);
      } catch {
        /* noop */
      }
    }

    return Promise.reject(err);
  }
);

// ─── Helpers typés (sucre syntaxique) ───────────────────────────────────────
export const apiGet = <T = unknown>(url: string, config?: AxiosRequestConfig) =>
  api.get<T>(url, config).then((r) => r.data);

export const apiPost = <T = unknown>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
) => api.post<T>(url, data, config).then((r) => r.data);

export const apiPut = <T = unknown>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
) => api.put<T>(url, data, config).then((r) => r.data);

export const apiPatch = <T = unknown>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig
) => api.patch<T>(url, data, config).then((r) => r.data);

export const apiDelete = <T = unknown>(url: string, config?: AxiosRequestConfig) =>
  api.delete<T>(url, config).then((r) => r.data);

export default api;
export { api };
