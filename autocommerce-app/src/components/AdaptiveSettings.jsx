import React from 'react';
import { useBlueprintConfig } from '../hooks/useBlueprintConfig';

/**
 * AdaptiveSettings — Wrapper pour adapter l'interface Settings selon le blueprint
 * Affiche/masque les sections en fonction du blueprint sélectionné
 */
export default function AdaptiveSettings({ children }) {
  const { blueprint, loading, isUIVisible, isModuleActive } = useBlueprintConfig();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-gray-400">Chargement de la configuration...</div>
      </div>
    );
  }

  if (!blueprint) {
    return (
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
        <p className="text-yellow-800">
          ⚠️ Veuillez d'abord sélectionner votre métier dans la configuration.
        </p>
      </div>
    );
  }

  // Créer un contexte pour les enfants
  const settingsContext = {
    blueprint,
    isUIVisible,
    isModuleActive,
  };

  // Cloner les enfants et passer le contexte
  return React.Children.map(children, (child) => {
    if (React.isValidElement(child)) {
      return React.cloneElement(child, { ...settingsContext });
    }
    return child;
  });
}
