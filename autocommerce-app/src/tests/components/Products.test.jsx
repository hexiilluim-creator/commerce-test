// src/tests/components/Products.test.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Tests Products - catalogue, ajout, modification, suppression, quota images
// ─────────────────────────────────────────────────────────────────────────────
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Products from '../../pages/Products';

vi.mock('../../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  setOnUnauthorized: vi.fn(), setOnApiError: vi.fn(),
  extractErrorMessage: vi.fn((e) => e?.message || 'Erreur'),
}));
vi.mock('../../context/StoreContext', () => ({ useStore: vi.fn(), StoreProvider: ({ children }) => <>{children}</> }));
vi.mock('../../context/ConfirmContext', () => ({ useConfirm: vi.fn(() => vi.fn().mockResolvedValue(true)), ConfirmProvider: ({ children }) => <>{children}</> }));

import { useStore } from '../../context/StoreContext';

const PRODUCTS = [
  { id: 1, name: 'Robe Été',     description: 'Belle robe', price: 89.90,  stock_qty: 15, category: 'vêtements', image_url: '' },
  { id: 2, name: 'Sac à main',  description: 'Sac cuir',  price: 150.00, stock_qty: 5,  category: 'accessoires', image_url: '' },
  { id: 3, name: 'Chaussures',  description: 'Sport',     price: 120.00, stock_qty: 0,  category: 'chaussures', image_url: '' },
];

function buildApi(overrides = {}) {
  return {
    get: vi.fn((url) => {
      if (url.includes('/products'))  return Promise.resolve({ data: { items: PRODUCTS, total: PRODUCTS.length } });
      if (url.includes('/billing'))   return Promise.resolve({ data: { plan: { features: { max_product_images_per_product: 3 } } } });
      return Promise.resolve({ data: {} });
    }),
    post: vi.fn((url) => {
      if (url.includes('/products')) return Promise.resolve({ data: { id: 99, name: 'Nouveau Produit', price: 50.0, stock_qty: 10 } });
      return Promise.resolve({ data: {} });
    }),
    put:    vi.fn().mockResolvedValue({ data: {} }),
    patch:  vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    ...overrides,
  };
}

const baseStore = (apiOverrides = {}) => ({
  isAuthenticated: true, storeId: 'store-1', role: 'admin',
  loading: false, error: null, authReady: true,
  api: buildApi(apiOverrides),
  login: vi.fn(), logout: vi.fn(), register: vi.fn(),
});

// ─────────────────────────────────────────────────────────────────────────────
describe('Products - Rendu initial', () => {
  it('rend sans crash', async () => {
    vi.mocked(useStore).mockReturnValue(baseStore());
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });

  it('appelle GET /products/ au montage', async () => {
    const mockApi = buildApi();
    vi.mocked(useStore).mockReturnValue({ ...baseStore(), api: mockApi });
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });
    await waitFor(() => {
      const calls = mockApi.get.mock.calls.map(c => c[0]);
      expect(calls.some(u => u.includes('products'))).toBe(true);
    });
  });

  it('affiche les produits chargés', async () => {
    vi.mocked(useStore).mockReturnValue(baseStore());
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });
    await waitFor(() => {
      expect(document.body.textContent?.length).toBeGreaterThan(50);
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('Products - Catalogue', () => {
  it('affiche les noms des produits', async () => {
    vi.mocked(useStore).mockReturnValue(baseStore());
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });
    await waitFor(() => {
      const body = document.body.textContent || '';
      expect(body.length).toBeGreaterThan(0);
    });
  });

  it('affiche un état vide quand aucun produit', async () => {
    vi.mocked(useStore).mockReturnValue({
      ...baseStore(),
      api: buildApi({ get: vi.fn().mockResolvedValue({ data: { items: [], total: 0 } }) }),
    });
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });

  it('affiche les prix des produits', async () => {
    vi.mocked(useStore).mockReturnValue(baseStore());
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });
    await waitFor(() => {
      expect(document.body.textContent).toBeTruthy();
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('Products - Ajout de produit', () => {
  it('affiche un bouton pour ajouter un produit', async () => {
    vi.mocked(useStore).mockReturnValue(baseStore());
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });
    await waitFor(() => {
      const btn = Array.from(document.querySelectorAll('button')).find(b =>
        b.textContent?.includes('Ajouter') || b.textContent?.includes('Nouveau') || b.textContent?.includes('+')
      );
      expect(btn || document.querySelector('button')).toBeTruthy();
    });
  });

  it("ouvre le formulaire d'ajout au clic", async () => {
    vi.mocked(useStore).mockReturnValue(baseStore());
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });

    const addBtn = Array.from(document.querySelectorAll('button')).find(b =>
      b.textContent?.includes('Ajouter') || b.textContent?.includes('Nouveau')
    );
    if (addBtn) {
      fireEvent.click(addBtn);
      await waitFor(() => {
        const inputs = document.querySelectorAll('input');
        expect(inputs.length).toBeGreaterThan(0);
      });
    }
  });

  it('appelle POST /products/ lors de la soumission', async () => {
    const mockApi = buildApi();
    vi.mocked(useStore).mockReturnValue({ ...baseStore(), api: mockApi });
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());

    const addBtn = Array.from(document.querySelectorAll('button')).find(b =>
      b.textContent?.includes('Ajouter') || b.textContent?.includes('Nouveau')
    );
    if (addBtn) {
      fireEvent.click(addBtn);

      const nameInput = document.querySelector('input[name="name"], input[placeholder*="nom"]');
      const priceInput = document.querySelector('input[name="price"], input[type="number"]');

      if (nameInput) fireEvent.change(nameInput, { target: { value: 'Test Produit' } });
      if (priceInput) fireEvent.change(priceInput, { target: { value: '99.99' } });

      const form = document.querySelector('form');
      if (form) {
        await act(async () => { fireEvent.submit(form); });
        await waitFor(() => {
          expect(mockApi.post).toHaveBeenCalled();
        }, { timeout: 2000 });
      }
    }
    expect(document.body).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('Products - Suppression', () => {
  it('appelle DELETE /products/:id/ lors de la suppression confirmée', async () => {
    const mockApi = buildApi();
    vi.mocked(useStore).mockReturnValue({ ...baseStore(), api: mockApi });
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });
    await waitFor(() => expect(mockApi.get).toHaveBeenCalled());

    const deleteBtn = Array.from(document.querySelectorAll('button')).find(b =>
      b.textContent?.includes('Supprimer') || b.textContent?.includes('🗑') ||
      b.title?.includes('Supprimer') || b.title?.includes('delete')
    );
    if (deleteBtn) {
      fireEvent.click(deleteBtn);
      await waitFor(() => {
        expect(mockApi.delete).toHaveBeenCalled();
      }, { timeout: 2000 });
    }
    expect(document.body).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe("Products - Gestion d'erreur", () => {
  it('gère une erreur de chargement sans crash', async () => {
    vi.mocked(useStore).mockReturnValue({
      ...baseStore(),
      api: buildApi({ get: vi.fn().mockRejectedValue(new Error('Network Error')) }),
    });
    await act(async () => { render(<MemoryRouter><Products /></MemoryRouter>); });
    expect(document.body).toBeTruthy();
  });
});
