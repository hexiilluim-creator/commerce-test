// src/tests/helpers/mockStore.jsx
// Expose le contexte StoreCtx pour les tests sans casser l'import réel.
import { createContext } from 'react';

// On ré-exporte le MÊME objet Context que StoreContext.jsx utilise en interne.
// Vitest hoiste les vi.mock, donc on accède ici à la valeur avant le module.
export const StoreCtxForTest = createContext(null);
