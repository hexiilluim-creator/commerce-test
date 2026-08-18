import { useState, useEffect } from 'react';
import { useStore } from '../context/StoreContext';

/**
 * Hook useBlueprintConfig
 * Fournit les configurations dynamiques en fonction du blueprint sélectionné
 */
export function useBlueprintConfig() {
  const { api } = useStore();
  const [blueprint, setBlueprint] = useState(null);
  const [storeBlueprint, setStoreBlueprint] = useState(null);
  const [uiVisibility, setUiVisibility] = useState({});
  const [activeModules, setActiveModules] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadBlueprintConfig();
  }, []);

  const loadBlueprintConfig = async () => {
    try {
      // 1. Charger la sélection du blueprint pour ce store
      const { data: sbData } = await api.get('/blueprints/my-store');
      if (!sbData) {
        setLoading(false);
        return;
      }

      setStoreBlueprint(sbData);

      // 2. Charger les détails du blueprint
      const { data: bpData } = await api.get(`/blueprints/${sbData.blueprint_id}`);
      setBlueprint(bpData);

      // 3. Calculer la visibilité UI (fusion blueprint + custom config)
      const visibility = bpData.ui_visibility || {};
      if (sbData.custom_config && sbData.custom_config.ui_visibility) {
        Object.assign(visibility, sbData.custom_config.ui_visibility);
      }
      setUiVisibility(visibility);

      // 4. Calculer les modules actifs
      let modules = bpData.modules_enabled || [];
      if (sbData.custom_config && sbData.custom_config.modules_enabled) {
        modules = sbData.custom_config.modules_enabled;
      }
      setActiveModules(modules);
    } catch (err) {
      console.error('Erreur lors du chargement de la config du blueprint:', err);
    } finally {
      setLoading(false);
    }
  };

  /**
   * Vérifie si un module est actif
   */
  const isModuleActive = (moduleName) => {
    return activeModules.includes(moduleName);
  };

  /**
   * Vérifie si une section UI doit être visible
   */
  const isUIVisible = (sectionName) => {
    return uiVisibility[sectionName] !== false;
  };

  /**
   * Récupère une valeur de configuration personnalisée
   */
  const getCustomConfig = (key, defaultValue = null) => {
    if (storeBlueprint && storeBlueprint.custom_config && storeBlueprint.custom_config[key]) {
      return storeBlueprint.custom_config[key];
    }
    return defaultValue;
  };

  /**
   * Récupère le prompt IA du blueprint
   */
  const getAIPrompt = () => {
    if (storeBlueprint && storeBlueprint.custom_config && storeBlueprint.custom_config.ai_prompt) {
      return storeBlueprint.custom_config.ai_prompt;
    }
    return blueprint?.default_ai_prompt || '';
  };

  return {
    blueprint,
    storeBlueprint,
    uiVisibility,
    activeModules,
    loading,
    isModuleActive,
    isUIVisible,
    getCustomConfig,
    getAIPrompt,
    reload: loadBlueprintConfig,
  };
}
