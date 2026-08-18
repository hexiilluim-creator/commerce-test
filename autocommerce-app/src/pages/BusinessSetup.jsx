import React, { useState, useEffect } from 'react';
import { useStore } from '../context/StoreContext';
import BlueprintSelector from '../components/BlueprintSelector';

/**
 * BusinessSetup — Page de configuration du métier
 * Affichée lors du premier lancement ou accessible depuis les paramètres
 */
export default function BusinessSetup() {
  const { api } = useStore();
  const [currentBlueprint, setCurrentBlueprint] = useState(null);
  const [showSelector, setShowSelector] = useState(false);

  useEffect(() => {
    loadCurrentBlueprint();
  }, []);

  const loadCurrentBlueprint = async () => {
    try {
      const { data } = await api.get('/blueprints/my-store');
      if (data) {
        setCurrentBlueprint(data.blueprint_id);
      } else {
        setShowSelector(true);
      }
    } catch (err) {
      console.error('Erreur:', err);
      setShowSelector(true);
    }
  };

  const handleBlueprintSelected = (blueprintId) => {
    setCurrentBlueprint(blueprintId);
    setShowSelector(false);
    // Recharger la page pour appliquer les changements
    setTimeout(() => window.location.reload(), 1000);
  };

  if (showSelector || !currentBlueprint) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          <BlueprintSelector onBlueprintSelected={handleBlueprintSelected} />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg p-6 shadow-sm border border-gray-100">
        <h2 className="text-2xl font-bold text-gray-900 mb-4">Configuration du Métier</h2>
        <p className="text-gray-600 mb-4">
          Votre métier a été configuré. Vous pouvez modifier ce choix à tout moment.
        </p>
        <button
          onClick={() => setShowSelector(true)}
          className="bg-indigo-600 text-white px-6 py-2 rounded-lg hover:bg-indigo-700 font-medium"
        >
          Changer de métier
        </button>
      </div>
    </div>
  );
}
