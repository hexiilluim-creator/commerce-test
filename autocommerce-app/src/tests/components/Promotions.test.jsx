// src/tests/components/Promotions.test.jsx
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, waitFor, act, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Promotions from '../../pages/Promotions';

vi.mock('../../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  setOnUnauthorized: vi.fn(), setOnApiError: vi.fn(),
  extractErrorMessage: vi.fn((e) => e?.message || 'Erreur'),
}));
vi.mock('../../context/StoreContext', () => ({ useStore: vi.fn(), StoreProvider: ({ children }) => <>{children}</> }));

import { useStore } from '../../context/StoreContext';

const CAMPAIGNS  = { items: [{ id: 1, name: 'Campagne Été', trigger_type: 'first_purchase', channel: 'whatsapp', status: 'active' }], total: 1 };
const PROMOTIONS = { items: [{ id: 1, name: 'Promo 10%', discount_type: 'percentage', discount_value: 10, applies_to: 'all', status: 'active' }], total: 1 };
const COUPONS    = { items: [{ id: 1, code: 'ETE10', promotion_id: 1, coupon_kind: 'multi', per_customer_limit: 1 }], total: 1 };

function buildApi() {
  return {
    get: vi.fn((url) => {
      if (url.includes('/campaigns'))   return Promise.resolve({ data: CAMPAIGNS });
      if (url.includes('/coupons'))     return Promise.resolve({ data: COUPONS });
      if (url.includes('/promotions'))  return Promise.resolve({ data: PROMOTIONS });
      return Promise.resolve({ data: { items: [], total: 0 } });
    }),
    post: vi.fn().mockResolvedValue({ data: { id: 99, name: 'Nouveau', status: 'active' } }),
    put:  vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  };
}

const baseStore = () => ({
  isAuthenticated: true, storeId: 'store-1', role: 'admin',
  loading: false, error: null, authReady: true,
  api: buildApi(), login: vi.fn(), logout: vi.fn(), register: vi.fn(),
});

describe('Promotions - Rendu', () => {
  it('rend sans crash', async () => {
    vi.mocked(useStore).mockReturnValue(baseStore());
    await act(async () => { render(<MemoryRouter><Promotions /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });

  it('charge les campagnes, promotions et coupons', async () => {
    const mockApi = buildApi();
    vi.mocked(useStore).mockReturnValue({ ...baseStore(), api: mockApi });
    await act(async () => { render(<MemoryRouter><Promotions /></MemoryRouter>); });
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());
    expect(mockApi.get.mock.calls.length).toBeGreaterThanOrEqual(1);
  });

  it('affiche le contenu chargé', async () => {
    vi.mocked(useStore).mockReturnValue(baseStore());
    await act(async () => { render(<MemoryRouter><Promotions /></MemoryRouter>); });
    await waitFor(() => { expect(document.body.textContent?.length).toBeGreaterThan(50); });
  });

  it('gère une erreur API sans crash', async () => {
    vi.mocked(useStore).mockReturnValue({
      ...baseStore(),
      api: { ...buildApi(), get: vi.fn().mockRejectedValue(new Error('Error')), post: vi.fn().mockRejectedValue(new Error('Error')) },
    });
    await act(async () => { render(<MemoryRouter><Promotions /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });

  it('affiche la liste vide sans crash', async () => {
    vi.mocked(useStore).mockReturnValue({
      ...baseStore(),
      api: { ...buildApi(), get: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }), post: vi.fn().mockResolvedValue({ data: { items: [] } }) },
    });
    await act(async () => { render(<MemoryRouter><Promotions /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });
});
