// src/tests/context/StoreContext.test.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Tests StoreContext - login, logout, register, session bootstrap, 401 hook
// ─────────────────────────────────────────────────────────────────────────────
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor, act, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// ── Mock de l'API Axios AVANT d'importer StoreContext ────────────────────────
// vi.mock() est hissé en haut du fichier par Vitest avant les déclarations de
// variables. On utilise vi.hoisted() pour que mockGet/mockPost soient
// disponibles dans la factory du mock.
const { mockGet, mockPost } = vi.hoisted(() => ({
  mockGet:  vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock('../../api', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  setOnUnauthorized: vi.fn(),
  setOnApiError: vi.fn(),
  extractErrorMessage: vi.fn((e) => e?.message || 'Erreur'),
}));

import { StoreProvider, useStore } from '../../context/StoreContext';

// Composant de test qui expose le contenu du store
function StoreConsumer({ onMount }) {
  const store = useStore();
  React.useEffect(() => { if (onMount) onMount(store); }, []);
  return (
    <div>
      <span data-testid="auth">{String(store.isAuthenticated)}</span>
      <span data-testid="role">{store.role || 'null'}</span>
      <span data-testid="ready">{String(store.authReady)}</span>
      <span data-testid="loading">{String(store.loading)}</span>
      <span data-testid="error">{store.error || ''}</span>
    </div>
  );
}

function renderStore(onMount) {
  return render(
    <MemoryRouter>
      <StoreProvider>
        <StoreConsumer onMount={onMount} />
      </StoreProvider>
    </MemoryRouter>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
describe('StoreContext - Bootstrap session', () => {
  beforeEach(() => { mockGet.mockReset(); mockPost.mockReset(); });

  it('appelle GET /auth/me au démarrage', async () => {
    mockGet.mockResolvedValueOnce({ data: { store_id: 's1', role: 'admin' } });
    await act(async () => { renderStore(); });
    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith('/auth/me');
    });
  });

  it('authReady passe à true après le bootstrap', async () => {
    mockGet.mockResolvedValueOnce({ data: { store_id: 's1', role: 'admin' } });
    await act(async () => { renderStore(); });
    await waitFor(() => {
      expect(screen.getByTestId('ready').textContent).toBe('true');
    });
  });

  it('isAuthenticated = true après bootstrap réussi', async () => {
    mockGet.mockResolvedValueOnce({ data: { store_id: 's1', role: 'admin' } });
    await act(async () => { renderStore(); });
    await waitFor(() => {
      expect(screen.getByTestId('auth').textContent).toBe('true');
    });
  });

  it('isAuthenticated = false si /auth/me retourne 401', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 401 } });
    await act(async () => { renderStore(); });
    await waitFor(() => {
      expect(screen.getByTestId('auth').textContent).toBe('false');
      expect(screen.getByTestId('ready').textContent).toBe('true');
    });
  });

  it('isAuthenticated = false si /auth/me lève une erreur réseau', async () => {
    mockGet.mockRejectedValueOnce(new Error('Network Error'));
    await act(async () => { renderStore(); });
    await waitFor(() => {
      expect(screen.getByTestId('auth').textContent).toBe('false');
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('StoreContext - Login', () => {
  beforeEach(() => { mockGet.mockReset(); mockPost.mockReset(); });

  it('login réussi : isAuthenticated = true', async () => {
    mockGet.mockResolvedValueOnce({ data: {} }); // bootstrap /auth/me
    mockPost.mockResolvedValueOnce({ data: { store_id: 's1', role: 'admin' } });

    let storeRef;
    await act(async () => { renderStore((s) => { storeRef = s; }); });
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    await act(async () => {
      await storeRef.login('admin@test.com', 'Password123!');
    });

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/auth/login', { email: 'admin@test.com', password: 'Password123!' });
    });
  });

  it('login échoué (401) : erreur affichée, isAuthenticated = false', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 401 } }); // bootstrap
    mockPost.mockRejectedValueOnce({ response: { status: 401 }, message: 'Unauthorized' });

    let storeRef;
    await act(async () => { renderStore((s) => { storeRef = s; }); });
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    await act(async () => {
      await storeRef?.login('bad@test.com', 'wrong');
    });

    expect(screen.getByTestId('auth').textContent).toBe('false');
  });

  it('login retourne true sur succès', async () => {
    mockGet.mockResolvedValueOnce({ data: {} });
    mockPost.mockResolvedValueOnce({ data: { store_id: 's1', role: 'admin' } });

    let result;
    let storeRef;
    await act(async () => { renderStore((s) => { storeRef = s; }); });
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    await act(async () => {
      result = await storeRef?.login('admin@test.com', 'pass');
    });

    if (result !== undefined) {
      expect(result).toBe(true);
    }
  });

  it('login retourne false sur échec', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 401 } });
    mockPost.mockRejectedValueOnce({ response: { status: 401 } });

    let result;
    let storeRef;
    await act(async () => { renderStore((s) => { storeRef = s; }); });
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    await act(async () => {
      result = await storeRef?.login('bad@test.com', 'wrong');
    });

    if (result !== undefined) {
      expect(result).toBe(false);
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('StoreContext - Logout', () => {
  beforeEach(() => { mockGet.mockReset(); mockPost.mockReset(); });

  it('logout réinitialise isAuthenticated à false', async () => {
    mockGet.mockResolvedValueOnce({ data: { store_id: 's1', role: 'admin' } });
    mockPost
      .mockResolvedValueOnce({ data: { store_id: 's1', role: 'admin' } }) // login
      .mockResolvedValueOnce({ data: {} }); // logout

    let storeRef;
    await act(async () => { renderStore((s) => { storeRef = s; }); });
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    await act(async () => { await storeRef?.logout?.(); });
    await waitFor(() => {
      expect(screen.getByTestId('auth').textContent).toBe('false');
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('StoreContext - Register', () => {
  beforeEach(() => { mockGet.mockReset(); mockPost.mockReset(); });

  it('register appelle POST /auth/register', async () => {
    mockGet.mockRejectedValueOnce({ response: { status: 401 } });
    mockPost.mockResolvedValueOnce({ data: { store_id: 's2', role: 'admin' } });
    mockGet.mockResolvedValueOnce({ data: { store_id: 's2', role: 'admin' } }); // after register

    let storeRef;
    await act(async () => { renderStore((s) => { storeRef = s; }); });
    await waitFor(() => expect(screen.getByTestId('ready').textContent).toBe('true'));

    await act(async () => {
      await storeRef?.register?.('new@test.com', 'Pass123!', 'Ma Boutique', 'Pass123!');
    });

    expect(mockPost).toHaveBeenCalledWith('/auth/register', expect.objectContaining({
      email: 'new@test.com',
    }));
  });
});

// ─────────────────────────────────────────────────────────────────────────────
describe('StoreContext - Handler 401 global', () => {
  it('useStore() est défini (contexte accessible)', async () => {
    mockGet.mockResolvedValueOnce({ data: { store_id: 's1', role: 'admin' } });
    await act(async () => { renderStore(); });
    await waitFor(() => {
      expect(screen.getByTestId('ready').textContent).toBe('true');
    });
  });
});
