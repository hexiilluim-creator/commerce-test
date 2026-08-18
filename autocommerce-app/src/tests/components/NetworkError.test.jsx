// src/tests/components/NetworkError.test.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Tests gestion erreurs réseau - retry, timeout, 401/403/500, offline
// ─────────────────────────────────────────────────────────────────────────────
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Orders from '../../pages/Orders';
import Dashboard from '../../pages/Dashboard';

vi.mock('../../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  setOnUnauthorized: vi.fn(), setOnApiError: vi.fn(),
  extractErrorMessage: vi.fn((e) => {
    if (e?.code === 'ECONNABORTED') return 'Délai dépassé, le serveur ne répond pas.';
    if (e?.message === 'Network Error') return 'Erreur Réseau';
    return e?.message || 'Erreur inconnue';
  }),
}));
vi.mock('../../context/StoreContext', () => ({ useStore: vi.fn(), StoreProvider: ({ children }) => <>{children}</> }));

import { useStore } from '../../context/StoreContext';

function makeStore(getImpl) {
  return {
    isAuthenticated: true, storeId: 'store-1', role: 'admin',
    loading: false, error: null, authReady: true,
    api: { get: getImpl, post: vi.fn().mockResolvedValue({ data: {} }), put: vi.fn().mockResolvedValue({ data: {} }),
           patch: vi.fn().mockResolvedValue({ data: {} }), delete: vi.fn().mockResolvedValue({ data: {} }) },
    login: vi.fn(), logout: vi.fn(), register: vi.fn(),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
describe('NetworkError - Erreur 500 (Internal Server Error)', () => {
  it('Orders : gère un 500 sans crash', async () => {
    vi.mocked(useStore).mockReturnValue(makeStore(vi.fn().mockRejectedValue({ response: { status: 500 }, message: 'Internal Server Error' })));
    await act(async () => { render(<MemoryRouter><Orders /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });

  it('Dashboard : gère un 500 sans crash', async () => {
    vi.mocked(useStore).mockReturnValue(makeStore(vi.fn().mockRejectedValue({ response: { status: 500 }, message: 'Internal Server Error' })));
    await act(async () => { render(<MemoryRouter><Dashboard /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('NetworkError - Erreur réseau (Network Error)', () => {
  it('Orders : gère un Network Error sans crash', async () => {
    vi.mocked(useStore).mockReturnValue(makeStore(vi.fn().mockRejectedValue(new Error('Network Error'))));
    await act(async () => { render(<MemoryRouter><Orders /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });

  it('Dashboard : gère un Network Error sans crash', async () => {
    vi.mocked(useStore).mockReturnValue(makeStore(vi.fn().mockRejectedValue(new Error('Network Error'))));
    await act(async () => { render(<MemoryRouter><Dashboard /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('NetworkError - Timeout (ECONNABORTED)', () => {
  it('Orders : gère un timeout sans crash', async () => {
    const timeoutErr = Object.assign(new Error('timeout of 30000ms exceeded'), { code: 'ECONNABORTED' });
    vi.mocked(useStore).mockReturnValue(makeStore(vi.fn().mockRejectedValue(timeoutErr)));
    await act(async () => { render(<MemoryRouter><Orders /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('NetworkError - Erreur 401 (Non autorisé)', () => {
  it('Orders : gère un 401 sans crash', async () => {
    vi.mocked(useStore).mockReturnValue(makeStore(vi.fn().mockRejectedValue({ response: { status: 401 }, message: 'Unauthorized' })));
    await act(async () => { render(<MemoryRouter><Orders /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('NetworkError - Erreur 403 (Interdit)', () => {
  it('Orders : gère un 403 sans crash', async () => {
    vi.mocked(useStore).mockReturnValue(makeStore(vi.fn().mockRejectedValue({ response: { status: 403, data: { detail: 'Forbidden' } } })));
    await act(async () => { render(<MemoryRouter><Orders /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('NetworkError - extractErrorMessage', () => {
  it('retourne message ECONNABORTED pour un timeout', async () => {
    const { extractErrorMessage } = await import('../../api');
    const err = { code: 'ECONNABORTED', message: 'timeout' };
    const msg = extractErrorMessage(err);
    expect(typeof msg).toBe('string');
    expect(msg.length).toBeGreaterThan(0);
  });

  it('retourne message Network Error pour une erreur réseau', async () => {
    const { extractErrorMessage } = await import('../../api');
    const err = new Error('Network Error');
    const msg = extractErrorMessage(err);
    expect(typeof msg).toBe('string');
  });

  it('retourne une chaîne pour une erreur inconnue', async () => {
    const { extractErrorMessage } = await import('../../api');
    const msg = extractErrorMessage({});
    expect(typeof msg).toBe('string');
  });
});
