import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import api from '../api';
import OptimizedCartV2 from '../components/OptimizedCartV2';
import {
  getActiveStorefrontStore,
  loadStorefrontCart,
  setActiveStorefrontStore,
} from '../utils/storefrontCart';

export default function StorefrontCartPage() {
  const [searchParams] = useSearchParams();
  const storeId = searchParams.get('store') || getActiveStorefrontStore();
  const [store, setStore] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const nextItems = loadStorefrontCart(storeId);
    setItems(nextItems);
  }, [storeId]);

  useEffect(() => {
    let cancelled = false;

    async function loadStore() {
      if (!storeId) {
        setError('Aucune boutique sélectionnée.');
        setLoading(false);
        return;
      }
      setLoading(true);
      setError('');
      try {
        const { data } = await api.get(`/storefront/${storeId}`);
        if (cancelled) return;
        setStore(data);
        setActiveStorefrontStore(storeId);
      } catch (err) {
        if (cancelled) return;
        setError(err?.response?.data?.detail || 'Impossible de charger la boutique.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadStore();
    return () => {
      cancelled = true;
    };
  }, [storeId]);

  const unitCount = useMemo(
    () => items.reduce((sum, item) => sum + (item.quantity || 1), 0),
    [items],
  );

  if (loading) {
    return (
      <div className="min-h-screen bg-[#f7f8fc] flex items-center justify-center text-gray-500">
        Chargement du panier...
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#f7f8fc] flex items-center justify-center p-6">
        <div className="max-w-lg w-full rounded-2xl border border-red-200 bg-white p-6 text-center shadow-sm space-y-3">
          <p className="text-lg font-semibold text-gray-900">Panier indisponible</p>
          <p className="text-sm text-red-600">{error}</p>
          <Link to="/" className="inline-flex items-center justify-center rounded-xl bg-gray-900 px-4 py-2 text-sm font-semibold text-white">
            Retour à l'accueil
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f7f8fc] py-8 px-4">
      <div className="max-w-5xl mx-auto space-y-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm text-gray-500">Panier public</p>
            <h1 className="text-3xl font-bold text-gray-900">{store?.name || 'Votre panier'}</h1>
            <p className="text-sm text-gray-500 mt-1">{unitCount} article(s) prêt(s) à être confirmés</p>
          </div>
          <Link
            to={storeId ? `/store/${storeId}` : '/'}
            className="inline-flex items-center justify-center rounded-xl border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50"
          >
            Continuer les achats
          </Link>
        </div>

        {items.length === 0 ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-gray-500 shadow-sm">
            Votre panier est vide.
          </div>
        ) : (
          <OptimizedCartV2
            items={items}
            store={store}
            storeId={storeId}
            initialOpen
            fullPage
          />
        )}
      </div>
    </div>
  );
}
