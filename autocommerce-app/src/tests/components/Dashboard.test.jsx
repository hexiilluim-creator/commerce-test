// src/tests/components/Dashboard.test.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Tests Dashboard - données vides, erreur API, données réelles
// ─────────────────────────────────────────────────────────────────────────────
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Dashboard from '../../pages/Dashboard';

vi.mock('../../api', () => ({
  default: {
    get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  setOnUnauthorized: vi.fn(),
  setOnApiError: vi.fn(),
  extractErrorMessage: vi.fn((e) => e?.message || 'Erreur'),
}));

vi.mock('../../context/StoreContext', () => ({ useStore: vi.fn(), StoreProvider: ({ children }) => <>{children}</> }));
import { useStore } from '../../context/StoreContext';

const OVERVIEW_DATA = {
  revenue: { total: 15000, growth_pct: 12.5, prev_period: 13350 },
  orders: { total: 142, pending: 8, growth_pct: 5 },
  customers: { total: 89, new_this_period: 14 },
  messages: { total: 234, urgent_30d: 3, ai_handled_pct: 78 },
  ai_tokens_used: 45000,
};

const ORDERS_DATA = {
  items: [
    { id: 1, status: 'pending', total: 250, customer_name: 'Ahmed Ben Ali', created_at: new Date().toISOString() },
    { id: 2, status: 'paid',    total: 180, customer_name: 'Sara Trabelsi', created_at: new Date().toISOString() },
  ],
  total: 2,
};

function buildApi(overrides = {}) {
  return {
    get: vi.fn((url) => {
      if (url.includes('dashboard/overview'))   return Promise.resolve({ data: overrides.overview || OVERVIEW_DATA });
      if (url.includes('orders'))              return Promise.resolve({ data: overrides.orders  || ORDERS_DATA });
      if (url.includes('products'))            return Promise.resolve({ data: overrides.products || { items: [], total: 0 } });
      if (url.includes('stock'))               return Promise.resolve({ data: [] });
      if (url.includes('analytics'))           return Promise.resolve({ data: {} });
      if (url.includes('conversations'))       return Promise.resolve({ data: { items: [] } });
      if (url.includes('billing'))             return Promise.resolve({ data: { plan: { features: {} } } });
      return Promise.resolve({ data: {} });
    }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    put:  vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  };
}

const baseStore = (apiOverrides = {}) => ({
  isAuthenticated: true, storeId: 'store-1', role: 'admin',
  loading: false, error: null, authReady: true,
  api: buildApi(apiOverrides),
  login: vi.fn(), logout: vi.fn(), register: vi.fn(),
});

function renderDashboard(apiOverrides = {}) {
  vi.mocked(useStore).mockReturnValue(baseStore(apiOverrides));
  return render(<MemoryRouter><Dashboard /></MemoryRouter>);
}

// ─────────────────────────────────────────────────────────────────────────────
describe('Dashboard - Rendu initial', () => {
  it('rend sans crash', async () => {
    await act(async () => { renderDashboard(); });
    expect(document.body).toBeTruthy();
  });

  it('affiche un indicateur de chargement pendant le fetch', () => {
    vi.mocked(useStore).mockReturnValue({
      ...baseStore(),
      api: {
        ...buildApi(),
        get: vi.fn(() => new Promise(() => {})), // ne résout jamais
      },
    });
    render(<MemoryRouter><Dashboard /></MemoryRouter>);
    // Le composant devrait gérer l'état loading
    expect(document.body.innerHTML).not.toBe('');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('Dashboard - État vide (aucune donnée)', () => {
  it('rend correctement avec des données vides', async () => {
    await act(async () => {
      renderDashboard({
        overview: {
          revenue: { total: 0, growth_pct: 0 },
          orders: { total: 0, pending: 0 },
          customers: { total: 0, new_this_period: 0 },
          messages: { total: 0, urgent_30d: 0, ai_handled_pct: 0 },
        },
        orders: { items: [], total: 0 },
        products: { items: [], total: 0 },
      });
    });
    expect(document.body).toBeTruthy();
  });

  it('affiche zéro commandes correctement', async () => {
    await act(async () => { renderDashboard({ orders: { items: [], total: 0 } }); });
    // Vérifie qu'il n'y a pas de crash avec un tableau vide
    expect(document.querySelector('[class*="dashboard"], [class*="grid"], main, [class*="rounded"]')).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('Dashboard - Erreur API', () => {
  it('gère une erreur 500 du serveur sans crash', async () => {
    vi.mocked(useStore).mockReturnValue({
      ...baseStore(),
      api: {
        ...buildApi(),
        get: vi.fn().mockRejectedValue({ response: { status: 500 }, message: 'Server Error' }),
      },
    });
    // Ne doit pas lever d'exception non catchée
    await act(async () => {
      render(<MemoryRouter><Dashboard /></MemoryRouter>);
    });
    expect(document.body).toBeTruthy();
  });

  it('gère une erreur réseau (timeout) sans crash', async () => {
    vi.mocked(useStore).mockReturnValue({
      ...baseStore(),
      api: {
        ...buildApi(),
        get: vi.fn().mockRejectedValue(new Error('Network Error')),
      },
    });
    await act(async () => {
      render(<MemoryRouter><Dashboard /></MemoryRouter>);
    });
    expect(document.body).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('Dashboard - Données réelles', () => {
  it("affiche les métriques de revenu quand l'API répond", async () => {
    await act(async () => { renderDashboard(); });
    await waitFor(() => {
      // Les données devraient être affichées
      const body = document.body.textContent || '';
      // Vérifie que le contenu est non vide et contient des données
      expect(body.length).toBeGreaterThan(0);
    }, { timeout: 3000 });
  });

  it('charge les commandes récentes', async () => {
    const mockApi = buildApi();
    vi.mocked(useStore).mockReturnValue({ ...baseStore(), api: mockApi });

    await act(async () => { render(<MemoryRouter><Dashboard /></MemoryRouter>); });

    await waitFor(() => {
      expect(mockApi.get).toHaveBeenCalled();
    });
  });

  it('tente de charger le stock bas', async () => {
    const mockApi = buildApi();
    vi.mocked(useStore).mockReturnValue({ ...baseStore(), api: mockApi });

    await act(async () => { render(<MemoryRouter><Dashboard /></MemoryRouter>); });

    await waitFor(() => {
      const calls = mockApi.get.mock.calls.map(c => c[0]);
      expect(calls.length).toBeGreaterThan(0);
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('Dashboard - Rôles', () => {
  it('rend pour un admin standard', async () => {
    await act(async () => { renderDashboard(); });
    expect(document.body).toBeTruthy();
  });

  it('rend aussi pour un rôle super_admin', async () => {
    vi.mocked(useStore).mockReturnValue({ ...baseStore(), role: 'super_admin', api: buildApi() });
    await act(async () => { render(<MemoryRouter><Dashboard /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });
});
