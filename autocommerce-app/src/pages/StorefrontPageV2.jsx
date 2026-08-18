import React, { useState, useEffect, useRef } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import api from '../api';
import OptimizedCartV2 from '../components/OptimizedCartV2';
import SocialContactButtons from '../components/SocialContactButtons';
import FloatingContactBar from '../components/FloatingContactBar';
import {
  loadStorefrontCart,
  saveStorefrontCart,
  setActiveStorefrontStore,
} from '../utils/storefrontCart';

// ══════════════════════════════════════════════════════════════════════════════
// Helpers
// ══════════════════════════════════════════════════════════════════════════════
const PAGE_SIZE = 12;

function getDaysSinceCreated(dateStr) {
  if (!dateStr) return 999;
  return Math.floor((Date.now() - new Date(dateStr).getTime()) / 86400000);
}

function getProductBadge(product, bestSellerIds) {
  if (product.stock_qty <= 0) return null;
  if (product.promo_price && product.promo_price < product.price)
    return { label: '💥 Promo', color: '#ef4444', bg: '#fef2f2' };
  if (bestSellerIds.has(product.id))
    return { label: '🔥 Best-seller', color: '#f59e0b', bg: '#fffbeb' };
  if (getDaysSinceCreated(product.created_at) <= 14)
    return { label: '🆕 Nouveau', color: '#6366f1', bg: '#eff6ff' };
  if (product.stock_qty > 0 && product.stock_qty <= 3)
    return { label: '📉 Dernières pièces', color: '#f97316', bg: '#fff7ed' };
  return null;
}

// ══════════════════════════════════════════════════════════════════════════════
// CATÉGORIES
// ══════════════════════════════════════════════════════════════════════════════
function CategoryBar({ categories, active, onSelect }) {
  const ref = useRef(null);
  if (!categories.length) return null;
  return (
    <div ref={ref} className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide" style={{ WebkitOverflowScrolling: 'touch', scrollbarWidth: 'none' }}>
      <style>{`.scrollbar-hide::-webkit-scrollbar{display:none}`}</style>
      <button
        onClick={() => onSelect(null)}
        className="flex-shrink-0 px-4 py-2 rounded-full text-sm font-semibold border transition-all"
        style={active === null
          ? { background: '#111827', color: '#fff', borderColor: '#111827' }
          : { background: '#fff', color: '#6b7280', borderColor: '#e5e7eb' }}
      >
        Tout
      </button>
      {categories.map(cat => (
        <button
          key={cat}
          onClick={() => onSelect(cat)}
          className="flex-shrink-0 px-4 py-2 rounded-full text-sm font-semibold border transition-all"
          style={active === cat
            ? { background: '#111827', color: '#fff', borderColor: '#111827' }
            : { background: '#fff', color: '#6b7280', borderColor: '#e5e7eb' }}
        >
          {cat}
        </button>
      ))}
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// HERO BANNER AMÉLIORÉ
// ══════════════════════════════════════════════════════════════════════════════
function HeroBannerV2({ store }) {
  if (store.banner_url) {
    return (
      <div className="relative h-56 overflow-hidden rounded-[24px] border border-white/20 shadow-[0_24px_60px_rgba(16,24,40,.18)] sm:h-72">
        <img src={store.banner_url} alt={store.name} className="w-full h-full object-cover" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent flex flex-col justify-end p-6">
          <p className="text-white font-black text-2xl sm:text-3xl leading-tight drop-shadow-lg">{store.name}</p>
          {store.description && (
            <p className="text-white/90 text-sm mt-2 line-clamp-2 drop-shadow">{store.description}</p>
          )}
          <div className="mt-4">
            <SocialContactButtons store={store} />
          </div>
        </div>
      </div>
    );
  }

  // Gradient fallback
  return (
    <div className="relative overflow-hidden rounded-[24px] border border-white/15 p-7 shadow-[0_24px_60px_rgba(16,24,40,.18)] sm:p-10"
      style={{ background: 'linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #db2777 100%)' }}>
      <div className="relative z-10">
        <p className="text-white font-black text-3xl leading-tight">{store.name}</p>
        {store.description && (
          <p className="text-white/90 text-base mt-3 line-clamp-2 max-w-md">{store.description}</p>
        )}
        <div className="flex items-center gap-2 mt-4 mb-6">
          <span className={`w-3 h-3 rounded-full ${store.is_open !== false ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
          <span className="text-white/80 text-sm font-medium">
            {store.is_open !== false ? 'Ouvert' : 'Fermé'}
          </span>
        </div>
        <div className="mt-6">
          <SocialContactButtons store={store} />
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// CARTE PRODUIT AMÉLIORÉE
// ══════════════════════════════════════════════════════════════════════════════
function ProductCard({ product, store, bestSellerIds, onAddToCart }) {
  const badge = getProductBadge(product, bestSellerIds);
  const currency = store?.currency || product.currency || 'TND';
  const locale = store?.language === 'ar' ? 'ar' : store?.language === 'en' ? 'en' : 'fr';
  const money = (value) => new Intl.NumberFormat(locale, { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 3 }).format(Number(value || 0));
  const hasImages = product.images && product.images.length > 0;
  const mainImage = hasImages ? product.images[0] : null;

  return (
    <div className="group overflow-hidden rounded-[22px] border border-[#e4e7ec] bg-white shadow-[0_4px_16px_rgba(16,24,40,.05)] transition-all hover:-translate-y-1 hover:border-[#c5c0ff] hover:shadow-[0_18px_42px_rgba(16,24,40,.12)]">
      {/* Image */}
      <div className="relative h-52 overflow-hidden bg-[#f1f3f8] sm:h-56">
        {mainImage ? (
          <img src={mainImage} alt={product.name} className="w-full h-full object-cover group-hover:scale-105 transition-transform" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-400">📦</div>
        )}
        {badge && (
          <div className="absolute top-3 right-3 px-3 py-1 rounded-full text-xs font-bold" style={{ color: badge.color, backgroundColor: badge.bg }}>
            {badge.label}
          </div>
        )}
        {product.stock_qty <= 0 && (
          <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
            <span className="text-white font-bold text-lg">Rupture de stock</span>
          </div>
        )}
      </div>

      {/* Contenu */}
      <div className="p-4">
        <h3 className="font-bold text-gray-900 line-clamp-2 mb-2">{product.name}</h3>
        {product.description && (
          <p className="text-xs text-gray-600 line-clamp-2 mb-3">{product.description}</p>
        )}

        {/* Prix */}
        <div className="flex items-baseline gap-2 mb-4">
          {product.promo_price && product.promo_price < product.price ? (
            <>
              <span className="text-lg font-bold text-red-600">{money(product.promo_price)}</span>
              <span className="text-sm text-gray-400 line-through">{money(product.price)}</span>
            </>
          ) : (
            <span className="text-lg font-bold text-gray-900">{money(product.price)}</span>
          )}
        </div>

        {/* Stock info */}
        <div className="mb-4">
          {product.stock_qty > 0 ? (
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-full bg-green-500"
                  style={{ width: `${Math.min((product.stock_qty / 10) * 100, 100)}%` }}
                />
              </div>
              <span className="text-xs text-gray-600">{product.stock_qty} en stock</span>
            </div>
          ) : (
            <span className="text-xs text-red-600 font-medium">Indisponible</span>
          )}
        </div>

        {/* Bouton */}
        <button
          onClick={() => onAddToCart(product)}
          disabled={product.stock_qty <= 0}
          className="w-full rounded-xl py-3 text-sm font-bold transition-all active:scale-[.98]"
          style={{
            background: product.stock_qty > 0 ? 'linear-gradient(135deg, #635bff, #4f46e5)' : '#e5e7eb',
            color: product.stock_qty > 0 ? '#fff' : '#9ca3af',
            cursor: product.stock_qty > 0 ? 'pointer' : 'not-allowed',
          }}
        >
          {product.stock_qty > 0 ? '🛒 Ajouter' : 'Indisponible'}
        </button>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE PRINCIPALE
// ══════════════════════════════════════════════════════════════════════════════
export default function StorefrontPageV2() {
  const { storeId } = useParams();
  const { t } = useTranslation();
  const [store, setStore] = useState(null);
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [activeCategory, setActiveCategory] = useState(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [nextCursor, setNextCursor] = useState(null);
  const [loading, setLoading] = useState(true);
  const [cart, setCart] = useState([]);
  const [bestSellerIds, setBestSellerIds] = useState(new Set());

  useEffect(() => {
    loadStore();
    loadProducts();
  }, [storeId, activeCategory, page]);

  useEffect(() => {
    setPage(1);
    setNextCursor(null);
  }, [storeId, activeCategory]);

  useEffect(() => {
    const savedCart = loadStorefrontCart(storeId);
    setCart(savedCart);
    setActiveStorefrontStore(storeId);
  }, [storeId]);

  useEffect(() => {
    saveStorefrontCart(storeId, cart);
  }, [storeId, cart]);

  const loadStore = async () => {
    try {
      const { data } = await api.get(`/storefront/${storeId}`);
      setStore(data);
      setActiveStorefrontStore(storeId);
    } catch (err) {
      console.error('Erreur chargement boutique:', err);
      setStore(null);
    }
  };

  const loadProducts = async () => {
    try {
      setLoading(true);
      const params = {
        category: activeCategory,
        limit: PAGE_SIZE,
        ...(page > 1 && nextCursor ? { cursor: nextCursor } : {}),
      };
      const { data } = await api.get(`/storefront/${storeId}/products`, { params });
      
      if (page === 1) {
        setProducts(data.products || []);
        const cats = [...new Set(data.products?.map(p => p.category).filter(Boolean))];
        setCategories(cats);
      } else {
        setProducts(prev => [...prev, ...(data.products || [])]);
      }
      
      setNextCursor(data.next_cursor || null);
      setHasMore(Boolean(data.has_more));
    } catch (err) {
      console.error('Erreur chargement produits:', err);
      if (page === 1) {
        setProducts([]);
        setCategories([]);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleAddToCart = (product) => {
    // Gérer les doublons et la quantité
    setCart(prev => {
      const existing = prev.find(item => item.id === product.id);
      if (existing) {
        return prev.map(item => 
          item.id === product.id ? { ...item, quantity: (item.quantity || 1) + 1 } : item
        );
      }
      return [...prev, { ...product, quantity: 1 }];
    });
  };

  if (!store) {
    return (
      <div className="flex items-center justify-center h-screen flex-col gap-4">
        <div className="text-gray-500">Chargement de la boutique...</div>
        <div className="text-sm text-gray-400">ID: {storeId}</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f7f8fc]">
      {/* Floating Contact Bar */}
      <FloatingContactBar store={store} />

      {/* Container */}
      <div className="mx-auto max-w-7xl space-y-7 px-4 py-5 sm:px-6 sm:py-8 lg:px-8">
        {/* Hero */}
        <HeroBannerV2 store={store} />

        {/* Catégories */}
        {categories.length > 0 && (
          <CategoryBar categories={categories} active={activeCategory} onSelect={setActiveCategory} />
        )}

        {cart.length > 0 && (
          <div className="flex justify-end">
            <Link
              to={`/cart?store=${encodeURIComponent(storeId)}`}
              className="inline-flex items-center gap-2 rounded-full bg-[#101828] px-4 py-2.5 text-sm font-bold text-white shadow-[0_10px_24px_rgba(16,24,40,.16)] transition hover:bg-[#243047] active:scale-[.98]"
            >
              <span>🛒</span>
              <span>Voir le panier ({cart.reduce((sum, item) => sum + (item.quantity || 1), 0)})</span>
            </Link>
          </div>
        )}

        {/* Grille produits */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {products.map(product => (
            <ProductCard
              key={product.id}
              product={product}
              store={store}
              bestSellerIds={bestSellerIds}
              onAddToCart={handleAddToCart}
            />
          ))}
        </div>

        {/* Load more */}
        {hasMore && (
          <div className="flex justify-center">
            <button
              onClick={() => setPage(p => p + 1)}
              disabled={loading}
              className="rounded-xl bg-[#101828] px-6 py-3 font-bold text-white shadow-lg transition-colors hover:bg-[#243047] disabled:opacity-60"
            >
              {loading ? 'Chargement...' : 'Charger plus'}
            </button>
          </div>
        )}
      </div>

      {/* Panier optimisé V2 */}
      {cart.length > 0 && (
        <OptimizedCartV2 items={cart} store={store} storeId={storeId} openOnItemsChange />
      )}
    </div>
  );
}
