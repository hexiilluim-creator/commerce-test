// src/context/StoreContext.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Contexte global d'authentification — basé EXCLUSIVEMENT sur cookies HttpOnly.
// • Plus aucune variable "token" stockée côté JS
// • isAuthenticated = boolean dérivé de la présence d'une session côté serveur
// • api unique importée depuis ../api (instance Axios centralisée)
// ─────────────────────────────────────────────────────────────────────────────
import React, {
  createContext,
  useState,
  useEffect,
  useContext,
  useCallback,
} from 'react';
import api, { setOnUnauthorized, extractErrorMessage } from '../api';

const StoreCtx = createContext(null);

export function StoreProvider({ children }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [storeId, setStoreId] = useState(null);
  const [store, setStore] = useState(null);
  const [role, setRole] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [authReady, setAuthReady] = useState(false);

  const clearAuthState = useCallback(() => {
    setIsAuthenticated(false);
    setStoreId(null);
    setStore(null);
    setRole(null);
    setError(null);
  }, []);

  // Recharge la configuration publique du magasin après une modification des paramètres.
  // Cela évite qu’un changement de devise reste uniquement local à la page Settings.
  const refreshStore = useCallback(async () => {
    try {
      const storeResponse = await api.get('/settings/store');
      setStore(storeResponse.data);
      return storeResponse.data;
    } catch {
      return null;
    }
  }, []);

  // ── Branche le handler 401 GLOBAL (déclenché par api.ts) ─────────────────
  useEffect(() => {
    setOnUnauthorized(() => {
      clearAuthState();
      const path = window.location.pathname;
      const isPublic =
        path === '/' || path === '/login' || path === '/reset-password'
        || path.startsWith('/boutique/') || path.startsWith('/store/');
      if (!isPublic) {
        window.location.href = '/login';
      }
    });
    return () => setOnUnauthorized(null);
  }, [clearAuthState]);

  // ── Bootstrap au démarrage : tente de récupérer la session ───────────────
  useEffect(() => {
    let isMounted = true;

    (async () => {
      try {
        const { data } = await api.get('/auth/me');
        if (!isMounted) return;
        setIsAuthenticated(true);
        setStoreId(data.store_id);
        setRole(data.role);
        try {
          const storeResponse = await api.get('/settings/store');
          if (isMounted) setStore(storeResponse.data);
        } catch {
          if (isMounted) setStore(null);
        }
      } catch {
        if (isMounted) clearAuthState();
      } finally {
        if (isMounted) setAuthReady(true);
      }
    })();

    return () => {
      isMounted = false;
    };
  }, [clearAuthState]);

  // ── Login ────────────────────────────────────────────────────────────────
  const login = useCallback(
    async (email, password) => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.post('/auth/login', { email, password });
        setIsAuthenticated(true);
        setStoreId(data.store_id);
        setRole(data.role);
        try {
          const storeResponse = await api.get('/settings/store');
          setStore(storeResponse.data);
        } catch {
          setStore(null);
        }
        setAuthReady(true);
        return true;
      } catch (e) {
        const status = e?.response?.status;
        let msg;
        if (status === 401 || status === 403) {
          msg = 'Email ou mot de passe incorrect';
        } else if (status >= 500) {
          msg = 'Erreur serveur, réessayer';
        } else {
          msg = extractErrorMessage(e);
        }
        setError(msg);
        clearAuthState();
        return false;
      } finally {
        setLoading(false);
      }
    },
    [clearAuthState]
  );

  // ── Register ─────────────────────────────────────────────────────────────
  const register = useCallback(
    async (email, password, storeName, confirmPassword) => {
      setLoading(true);
      setError(null);
      try {
        const { data } = await api.post('/auth/register', {
          email,
          password,
          confirm_password: confirmPassword,
          store_name: storeName,
        });
        setIsAuthenticated(true);
        setStoreId(data.store_id);
        setRole(data.role);
        try {
          const storeResponse = await api.get('/settings/store');
          setStore(storeResponse.data);
        } catch {
          setStore(null);
        }
        setAuthReady(true);
        await api.get('/auth/me');
        return true;
      } catch (e) {
        const status = e?.response?.status;
        let msg;
        if (status === 409 || status === 400) {
          msg = extractErrorMessage(e) || 'Erreur lors de l\'inscription';
        } else if (status >= 500) {
          msg = 'Erreur serveur, réessayer';
        } else {
          msg = extractErrorMessage(e);
        }
        setError(msg);
        clearAuthState();
        return false;
      } finally {
        setLoading(false);
      }
    },
    [clearAuthState]
  );

  // ── Logout ───────────────────────────────────────────────────────────────
  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } catch {
      /* on continue même si l'appel échoue (cookie expiré) */
    } finally {
      clearAuthState();
      setAuthReady(true);
    }
  }, [clearAuthState]);

  // ── Compatibilité ascendante : ancien champ "token" exposé en lecture ────
  // (certains anciens composants pourraient encore le tester ; on renvoie un
  //  booléen sentinel pour ne rien casser → équivalent à isAuthenticated)
  const value = {
    isAuthenticated,
    token: isAuthenticated ? 'cookie' : null, // legacy compat
    storeId,
    store,
    role,
    loading,
    error,
    authReady,
    login,
    register,
    logout,
    refreshStore,
    api,
  };

  return <StoreCtx.Provider value={value}>{children}</StoreCtx.Provider>;
}

export const useStore = () => {
  const ctx = useContext(StoreCtx);
  if (!ctx) throw new Error('useStore must be used inside StoreProvider');
  return ctx;
};

export { api };
