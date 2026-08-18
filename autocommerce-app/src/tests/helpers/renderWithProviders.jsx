// src/tests/helpers/renderWithProviders.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Wrapper universel pour les tests — fournit ToastProvider, ConfirmProvider
// et MemoryRouter. StoreContext est mocké au niveau de chaque fichier de test
// avec vi.mock('../../context/StoreContext').
// ─────────────────────────────────────────────────────────────────────────────
import React from 'react';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../context/ToastContext';
import { ConfirmProvider } from '../../context/ConfirmContext';

/**
 * renderWithProviders(ui, options)
 *
 * @param {React.ReactElement} ui
 * @param {object}  options.initialPath   — route initiale MemoryRouter (défaut "/")
 * @param {object}  options.renderOptions — passés à RTL render()
 */
export function renderWithProviders(ui, { initialPath = '/', renderOptions = {} } = {}) {
  function Wrapper({ children }) {
    return (
      <MemoryRouter initialEntries={[initialPath]}>
        <ToastProvider>
          <ConfirmProvider>
            {children}
          </ConfirmProvider>
        </ToastProvider>
      </MemoryRouter>
    );
  }
  return render(ui, { wrapper: Wrapper, ...renderOptions });
}

/**
 * buildMockStore(overrides) — crée un objet store mock complet.
 */
export function buildMockStore(overrides = {}) {
  return {
    isAuthenticated: true,
    storeId: 'store-abc-123',
    role: 'admin',
    loading: false,
    error: null,
    authReady: true,
    api: buildMockApi(overrides.apiResponses),
    login: vi.fn().mockResolvedValue(true),
    logout: vi.fn().mockResolvedValue(undefined),
    register: vi.fn().mockResolvedValue(true),
    ...overrides,
  };
}

/**
 * buildMockApi(responses) — crée un objet api (axios-like) avec réponses
 * configurables.
 *
 * responses = {
 *   GET:    { '/orders/': { items: [], total: 0 } },
 *   POST:   { '/auth/login': { store_id: 'x', role: 'admin' } },
 *   PATCH:  { '/orders/:id/status': {} },
 *   DELETE: { '/products/:id/': {} },
 * }
 *
 * Les clés peuvent utiliser ':id' comme wildcard.
 * Passer une instance Error pour simuler une erreur réseau.
 */
export function buildMockApi(responses = {}) {
  const resolve = (method, url) => {
    const byMethod = responses[method] || {};
    // Cherche d'abord URL exacte, puis version normalisée (segments numériques → :id)
    const normalised = url.replace(/\/\d+/g, '/:id');
    const res = byMethod[url] ?? byMethod[normalised];
    if (res === undefined) return Promise.resolve({ data: {} });
    if (res instanceof Error) return Promise.reject(res);
    return Promise.resolve({ data: res });
  };

  return {
    get:    vi.fn((url) => resolve('GET',    url)),
    post:   vi.fn((url) => resolve('POST',   url)),
    put:    vi.fn((url) => resolve('PUT',    url)),
    patch:  vi.fn((url) => resolve('PATCH',  url)),
    delete: vi.fn((url) => resolve('DELETE', url)),
  };
}
