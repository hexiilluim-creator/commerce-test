import React, { useState, useEffect } from 'react';
import { useStore } from '../context/StoreContext';
import { useTranslation } from 'react-i18next';

/**
 * BlueprintSelector — Composant pour sélectionner un Blueprint Métier
 * Affiche les blueprints disponibles sous forme de cartes interactives
 */
export default function BlueprintSelector({ onBlueprintSelected }) {
  const { api } = useStore();
  const { t } = useTranslation();
  const [blueprints, setBlueprints] = useState([]);
  const [selectedBlueprint, setSelectedBlueprint] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    loadBlueprints();
    loadCurrentBlueprint();
  }, []);

  const loadBlueprints = async () => {
    try {
      const { data } = await api.get('/blueprints/');
      setBlueprints(data || []);
    } catch (err) {
      console.error('Erreur lors du chargement des blueprints:', err);
      setToast({ msg: 'Erreur lors du chargement des blueprints', type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const loadCurrentBlueprint = async () => {
    try {
      const { data } = await api.get('/blueprints/my-store');
      if (data) {
        setSelectedBlueprint(data.blueprint_id);
      }
    } catch (err) {
      console.error('Erreur lors du chargement du blueprint actuel:', err);
    }
  };

  const handleSelectBlueprint = async (blueprintId) => {
    setSaving(true);
    try {
      await api.post('/blueprints/select', { blueprint_id: blueprintId });
      setSelectedBlueprint(blueprintId);
      setToast({ msg: 'Blueprint sélectionné avec succès ✅', type: 'success' });
      if (onBlueprintSelected) {
        onBlueprintSelected(blueprintId);
      }
    } catch (err) {
      setToast({ msg: 'Erreur lors de la sélection du blueprint', type: 'error' });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-gray-400">Chargement des blueprints...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="text-center mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">🏗️ Sélectionnez votre métier</h1>
        <p className="text-gray-600">Choisissez le type d'activité qui correspond à votre boutique. Nous configurerons AutoCommerce spécifiquement pour vous.</p>
      </div>

      {/* Toast notification */}
      {toast && (
        <div
          className={`fixed top-4 right-4 px-6 py-3 rounded-lg text-white z-50 ${
            toast.type === 'error' ? 'bg-red-500' : 'bg-green-500'
          }`}
        >
          {toast.msg}
        </div>
      )}

      {/* Grille de blueprints */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {blueprints.map((blueprint) => (
          <div
            key={blueprint.id}
            onClick={() => handleSelectBlueprint(blueprint.id)}
            className={`relative p-6 rounded-xl border-2 cursor-pointer transition-all ${
              selectedBlueprint === blueprint.id
                ? 'border-indigo-600 bg-indigo-50 shadow-lg'
                : 'border-gray-200 bg-white hover:border-indigo-300 hover:shadow-md'
            } ${saving ? 'opacity-50 pointer-events-none' : ''}`}
          >
            {/* Icône */}
            <div className="text-5xl mb-4">{blueprint.icon}</div>

            {/* Titre */}
            <h3 className="text-xl font-bold text-gray-900 mb-2">{blueprint.name}</h3>

            {/* Description */}
            <p className="text-sm text-gray-600 mb-4">{blueprint.description}</p>

            {/* Modules activés */}
            <div className="mb-4">
              <p className="text-xs font-semibold text-gray-500 mb-2">Modules inclus :</p>
              <div className="flex flex-wrap gap-2">
                {blueprint.modules_enabled.map((module) => (
                  <span
                    key={module}
                    className="px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded-full"
                  >
                    {module === 'appointments' && '📅 RDV'}
                    {module === 'stock' && '📦 Stock'}
                    {module === 'oem_parts' && '🔧 Pièces OEM'}
                  </span>
                ))}
              </div>
            </div>

            {/* Bouton de sélection */}
            <button
              className={`w-full py-2 rounded-lg font-semibold transition-colors ${
                selectedBlueprint === blueprint.id
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-100 text-gray-900 hover:bg-gray-200'
              }`}
              disabled={saving}
            >
              {selectedBlueprint === blueprint.id ? '✅ Sélectionné' : 'Sélectionner'}
            </button>
          </div>
        ))}
      </div>

      {/* Message de confirmation */}
      {selectedBlueprint && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
          <p className="text-green-800">
            ✅ Votre métier a été configuré. Vous pouvez maintenant accéder à tous les paramètres spécifiques dans votre tableau de bord.
          </p>
        </div>
      )}
    </div>
  );
}
