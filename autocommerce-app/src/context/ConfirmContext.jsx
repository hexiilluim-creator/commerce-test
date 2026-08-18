// src/context/ConfirmContext.jsx
// ─────────────────────────────────────────────────────────────────────────────
// AUDIT FIX : window.confirm()/confirm() natif utilisé dans 4 pages
// (Products, Appointments, PaymentLinks, Settings) pour les suppressions.
// Un rapport de test utilisateur automatisé a signalé un "timeout navigateur"
// lors de la suppression d'un produit — cause probable : les outils de test
// automatisés ne peuvent généralement pas interagir avec les dialogues natifs
// du navigateur (confirm/alert/prompt), qui ne font pas partie du DOM/arbre
// d'accessibilité de la page. Au-delà de ce cas, confirm() natif est bloquant
// pour la boucle d'événements JS, non stylable, et incohérent d'un navigateur
// à l'autre — ToastContext avait déjà remplacé tous les alert() natifs du
// projet pour ces mêmes raisons ; confirm() avait été oublié dans ce nettoyage.
//
// API pensée pour un remplacement minimal des call sites :
//   const ok = await confirm("Supprimer ce produit ?");
//   if (!ok) return;
// ─────────────────────────────────────────────────────────────────────────────
import React, { createContext, useCallback, useContext, useRef, useState } from 'react';

const ConfirmCtx = createContext(null);

export function ConfirmProvider({ children }) {
  const [dialog, setDialog] = useState(null); // { message, resolve }
  const resolverRef = useRef(null);

  const confirm = useCallback((message) => {
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setDialog({ message });
    });
  }, []);

  const handleChoice = (result) => {
    setDialog(null);
    if (resolverRef.current) {
      resolverRef.current(result);
      resolverRef.current = null;
    }
  };

  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      {dialog && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 px-4"
          role="alertdialog"
          aria-modal="true"
          onKeyDown={(e) => {
            if (e.key === 'Escape') handleChoice(false);
          }}
        >
          <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl">
            <p className="mb-4 text-sm text-gray-800 whitespace-pre-line">{dialog.message}</p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => handleChoice(false)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                Annuler
              </button>
              <button
                type="button"
                autoFocus
                onClick={() => handleChoice(true)}
                className="rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
              >
                Confirmer
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmCtx.Provider>
  );
}

export function useConfirm() {
  const ctx = useContext(ConfirmCtx);
  if (!ctx) {
    throw new Error('useConfirm() doit être utilisé dans un <ConfirmProvider>');
  }
  return ctx;
}
