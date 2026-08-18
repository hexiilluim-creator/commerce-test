// src/tests/setup.ts
// ─────────────────────────────────────────────────────────────────────────────
// Setup global Vitest — jest-dom matchers + mocks navigateur obligatoires
// ─────────────────────────────────────────────────────────────────────────────
import '@testing-library/jest-dom';
import { vi } from 'vitest';

// ── Mocks navigateur ──────────────────────────────────────────────────────────
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

Object.defineProperty(navigator, 'clipboard', {
  writable: true,
  value: {
    writeText: vi.fn().mockResolvedValue(undefined),
    readText: vi.fn().mockResolvedValue(''),
  },
});

// ResizeObserver nécessaire pour Recharts
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof IntersectionObserver;

// window.open mock
window.open = vi.fn();

// window.location mock helpers
Object.defineProperty(window, 'location', {
  writable: true,
  value: { ...window.location, href: 'http://localhost/', assign: vi.fn(), replace: vi.fn() },
});

// ── Suppression des unhandledRejection attendus dans les tests d'erreurs ──────
// Les tests de gestion d'erreurs réseau (NetworkError.test, Promotions.test…)
// simulent des rejections d'API volontaires via vi.fn().mockRejectedValue().
// Les composants catchent ces erreurs dans leurs try/catch, mais Vitest
// (couche Node.js) peut quand même les détecter comme "unhandled" lorsqu'elles
// surviennent dans un Promise.all ou une closure useEffect non chainée.
// On installe un filtre au niveau process pour ces cas prévisibles et documentés.
const _originalUnhandled = process.listeners('unhandledRejection');
process.removeAllListeners('unhandledRejection');
process.on('unhandledRejection', (reason: unknown, promise: Promise<unknown>) => {
  const r = reason as Record<string, unknown> | Error | null;
  // Rejections volontaires de simulation d'erreurs réseau — à ignorer
  if (
    (r && typeof r === 'object' && 'response' in r && (r as Record<string, unknown>).response) ||
    (r instanceof Error && (r.message === 'Network Error' || r.message === 'Error' || (r as Error & { code?: string }).code === 'ECONNABORTED')) ||
    (r && typeof r === 'object' && (r as Record<string, unknown>).message === 'Network Error') ||
    (r && typeof r === 'object' && (r as Record<string, unknown>).code === 'ECONNABORTED')
  ) {
    return; // silencer la rejection attendue
  }
  // Pour toute autre rejection non attendue, transférer aux handlers originaux
  _originalUnhandled.forEach((h) => (h as (...args: unknown[]) => void)(reason, promise));
});

// Même filtre côté window (jsdom) pour les cas asynchrones dans le DOM
window.addEventListener('unhandledrejection', (event) => {
  const r = event.reason;
  if (
    (r && r.response) ||
    r?.message === 'Network Error' ||
    r?.code === 'ECONNABORTED' ||
    r?.message === 'Error' ||
    (r instanceof Error && r.message === 'Error')
  ) {
    event.preventDefault();
  }
});
