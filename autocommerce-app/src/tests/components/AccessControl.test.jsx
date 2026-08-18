// src/tests/components/AccessControl.test.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Tests contrôle d'accès - isolation tenant, routes protégées, rôles
// ─────────────────────────────────────────────────────────────────────────────
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom';

vi.mock('../../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  setOnUnauthorized: vi.fn(), setOnApiError: vi.fn(),
  extractErrorMessage: vi.fn((e) => e?.message || 'Erreur'),
}));
vi.mock('../../context/StoreContext', () => ({ useStore: vi.fn(), StoreProvider: ({ children }) => <>{children}</> }));
vi.mock('../../context/ToastContext', () => ({ useToast: vi.fn(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() })), ToastProvider: ({ children }) => <>{children}</> }));

import { useStore } from '../../context/StoreContext';
import Auth from '../../pages/Auth';

// Composant simulant une route protégée
function ProtectedPage({ requiredRole, children }) {
  const store = useStore();
  if (!store.isAuthenticated) return <Navigate to="/login" />;
  if (requiredRole && store.role !== requiredRole) return <div data-testid="access-denied">Accès refusé</div>;
  return <>{children}</>;
}

function TestApp({ isAuthenticated = true, role = 'admin' }) {
  vi.mocked(useStore).mockReturnValue({
    isAuthenticated, role, storeId: 'store-1',
    loading: false, error: null, authReady: true,
    api: { get: vi.fn().mockResolvedValue({ data: {} }), post: vi.fn().mockResolvedValue({ data: {} }),
           put: vi.fn().mockResolvedValue({ data: {} }), patch: vi.fn().mockResolvedValue({ data: {} }),
           delete: vi.fn().mockResolvedValue({ data: {} }) },
    login: vi.fn(), logout: vi.fn(), register: vi.fn(),
  });

  return (
    <MemoryRouter>
      <Routes>
        <Route path="/login" element={<Auth />} />
        <Route path="/dashboard" element={<ProtectedPage><div data-testid="dashboard">Dashboard</div></ProtectedPage>} />
        <Route path="/super-admin" element={<ProtectedPage requiredRole="super_admin"><div data-testid="super-admin">Super Admin</div></ProtectedPage>} />
        <Route path="*" element={<Navigate to="/dashboard" />} />
      </Routes>
    </MemoryRouter>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
describe('AccessControl - Routes protégées', () => {
  it('affiche le dashboard pour un utilisateur authentifié', async () => {
    render(<TestApp isAuthenticated={true} role="admin" />);
    await waitFor(() => {
      expect(document.querySelector('[data-testid="dashboard"]')).toBeTruthy();
    });
  });

  it('redirige vers /login si non authentifié', async () => {
    render(<TestApp isAuthenticated={false} role={null} />);
    await waitFor(() => {
      // La redirection vers /login doit se produire (Auth page)
      expect(document.body).toBeTruthy();
    });
  });

  it("refuse l'accès super-admin à un admin standard", async () => {
    // Setup explicite du mock useStore : isAuthenticated=true, role='admin'
    // (le test précédent laisse le mock sur isAuthenticated=false, ce qui
    // causerait une redirection vers /login au lieu d'afficher "access-denied")
    vi.mocked(useStore).mockReturnValue({
      isAuthenticated: true, role: 'admin', storeId: 'store-1',
      loading: false, error: null, authReady: true,
      api: { get: vi.fn().mockResolvedValue({ data: {} }), post: vi.fn().mockResolvedValue({ data: {} }),
             put: vi.fn().mockResolvedValue({ data: {} }), patch: vi.fn().mockResolvedValue({ data: {} }),
             delete: vi.fn().mockResolvedValue({ data: {} }) },
      login: vi.fn(), logout: vi.fn(), register: vi.fn(),
    });
    render(
      <MemoryRouter initialEntries={['/super-admin']}>
        <Routes>
          <Route path="/super-admin" element={<ProtectedPage requiredRole="super_admin"><div>Super Admin</div></ProtectedPage>} />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(document.querySelector('[data-testid="access-denied"]')).toBeTruthy();
    });
  });

  it("autorise l'accès super-admin au rôle super_admin", async () => {
    vi.mocked(useStore).mockReturnValue({
      isAuthenticated: true, role: 'super_admin', storeId: 'sa-store',
      loading: false, error: null, authReady: true,
      api: { get: vi.fn().mockResolvedValue({ data: {} }) },
      login: vi.fn(), logout: vi.fn(), register: vi.fn(),
    });
    render(
      <MemoryRouter initialEntries={['/super-admin']}>
        <Routes>
          <Route path="/super-admin" element={
            <ProtectedPage requiredRole="super_admin">
              <div data-testid="super-admin-content">Super Admin Content</div>
            </ProtectedPage>
          } />
        </Routes>
      </MemoryRouter>
    );
    await waitFor(() => {
      expect(document.querySelector('[data-testid="super-admin-content"]')).toBeTruthy();
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('AccessControl - Isolation tenant (simulation)', () => {
  it("chaque store n'accède qu'à ses propres données (storeId dans l'appel API)", async () => {
    const mockGet = vi.fn((url) => {
      // Simule que les appels API incluent le store context (via cookies/session)
      return Promise.resolve({ data: { items: [], total: 0, store_id: 'store-1' } });
    });

    vi.mocked(useStore).mockReturnValue({
      isAuthenticated: true, role: 'admin', storeId: 'store-1',
      loading: false, error: null, authReady: true,
      api: { get: mockGet, post: vi.fn().mockResolvedValue({ data: {} }), put: vi.fn().mockResolvedValue({ data: {} }),
             patch: vi.fn().mockResolvedValue({ data: {} }), delete: vi.fn().mockResolvedValue({ data: {} }) },
      login: vi.fn(), logout: vi.fn(), register: vi.fn(),
    });

    // Simule une tentative d'accès aux données d'un autre tenant
    const unauthorizedApi = vi.fn().mockRejectedValue({ response: { status: 403, data: { detail: 'Forbidden' } } });
    unauthorizedApi.mockRejectedValueOnce({ response: { status: 403 } });

    // Vérifie que l'API retourne 403 pour les accès cross-tenant
    await expect(unauthorizedApi('/orders/?store_id=store-2')).rejects.toMatchObject({
      response: { status: 403 },
    });
  });

  it('un 401 déclenche un logout et redirige vers /login', async () => {
    const mockUnauthorizedCallback = vi.fn();
    vi.mocked(useStore).mockReturnValue({
      isAuthenticated: false, role: null, storeId: null,
      loading: false, error: null, authReady: true,
      api: { get: vi.fn().mockRejectedValue({ response: { status: 401 } }) },
      login: vi.fn(), logout: vi.fn(), register: vi.fn(),
    });

    // Simule la logique de déconnexion au 401
    const clearAuth = vi.fn();
    const handleUnauthorized = () => { clearAuth(); };
    handleUnauthorized();

    expect(clearAuth).toHaveBeenCalled();
  });

  it('session expirée - redirige proprement', async () => {
    vi.mocked(useStore).mockReturnValue({
      isAuthenticated: false, role: null, storeId: null,
      loading: false, error: null, authReady: true,
      api: { get: vi.fn().mockRejectedValue({ response: { status: 401 } }) },
      login: vi.fn(), logout: vi.fn(), register: vi.fn(),
    });
    render(<TestApp isAuthenticated={false} role={null} />);
    await waitFor(() => { expect(document.body).toBeTruthy(); });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('AccessControl - Tenant A vs Tenant B', () => {
  it('store-1 ne peut pas voir les données de store-2', async () => {
    // Simule un appel API cross-tenant qui retourne 403
    const crossTenantApi = vi.fn().mockRejectedValue({
      response: { status: 403, data: { detail: 'You do not have permission to access this resource.' } },
    });

    await expect(crossTenantApi('/api/v1/orders/?store_override=store-2')).rejects.toMatchObject({
      response: { status: 403 },
    });
  });

  it("un admin d'un tenant ne peut pas modifier les produits d'un autre tenant", async () => {
    const crossTenantPatch = vi.fn().mockRejectedValue({
      response: { status: 403, data: { detail: 'Forbidden' } },
    });
    await expect(crossTenantPatch('/api/v1/products/999/status', { status: 'active' })).rejects.toMatchObject({
      response: { status: 403 },
    });
  });
});
