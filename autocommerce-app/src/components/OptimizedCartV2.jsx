import React, { useEffect, useMemo, useRef, useState } from 'react';
import api from '../api';
import { normalizeCartItems, computeCartTotal, generateOrderMessage, getContactUrl } from '../utils/cartOrderMessage';

const formatMoney = (amount, currency = 'TND', locale = 'fr-TN') => new Intl.NumberFormat(locale, {
  style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 3,
}).format(Number(amount || 0));

/**
 * OptimizedCartV2 — Panier optimisé avec aperçu promotions/coupons
 */
export default function OptimizedCartV2({ items, store, storeId, openOnItemsChange = false, initialOpen = false, fullPage = false }) {
  const [isOpen, setIsOpen] = useState(initialOpen || fullPage);
  const previousCountRef = useRef(items?.length || 0);
  const [customerName, setCustomerName] = useState('');
  const [customerPhone, setCustomerPhone] = useState('');
  const [couponCode, setCouponCode] = useState('');
  const [preview, setPreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [directOrderLoading, setDirectOrderLoading] = useState(false);
  const [directOrderError, setDirectOrderError] = useState('');
  const [directOrderSuccess, setDirectOrderSuccess] = useState(null);

  useEffect(() => {
    if (!openOnItemsChange) {
      previousCountRef.current = items?.length || 0;
      return;
    }
    const currentCount = items?.length || 0;
    if (currentCount > previousCountRef.current) {
      setIsOpen(true);
    }
    previousCountRef.current = currentCount;
  }, [items, openOnItemsChange]);

  useEffect(() => {
    if (fullPage) {
      setIsOpen(true);
    }
  }, [fullPage]);

  if (!items || items.length === 0) return null;

  const normalizedItems = useMemo(() => normalizeCartItems(items), [items]);

  const currency = store?.currency || 'TND';
  const locale = store?.language === 'ar' ? 'ar' : store?.language === 'en' ? 'en' : 'fr';
  const money = (amount) => formatMoney(amount, currency, locale);
  const baseTotal = computeCartTotal(normalizedItems);
  const effectiveItems = preview?.items || normalizedItems;
  const effectiveTotal = preview?.pricing?.total_amount ?? baseTotal;
  const effectiveDiscount = preview?.discount_amount ?? 0;

  const applyCouponPreview = async () => {
    if (!storeId) return;
    setLoadingPreview(true);
    setPreviewError('');
    try {
      const { data } = await api.post(`/storefront/${storeId}/promotions/preview`, {
        items: normalizedItems,
        coupon_codes: couponCode.trim() ? [couponCode.trim()] : [],
        channel: 'storefront',
        customer_name: customerName || undefined,
        customer_phone: customerPhone || undefined,
      });
      setPreview(data);
    } catch (err) {
      setPreview(null);
      setPreviewError(err?.response?.data?.detail || 'Coupon invalide ou promotion indisponible');
    } finally {
      setLoadingPreview(false);
    }
  };

  const buildOrderMessage = () => generateOrderMessage({
    effectiveItems,
    customerName,
    customerPhone,
    appliedPromotions: preview?.applied_promotions,
    couponCode,
    effectiveDiscount,
    effectiveTotal,
    store,
  });

  const buildContactUrl = (channel) => getContactUrl(channel, store, buildOrderMessage());

  const submitDirectOrder = async () => {
    if (!storeId || customerPhone.trim().length < 5) {
      setDirectOrderError('Veuillez renseigner un numéro de téléphone valide.');
      return;
    }
    setDirectOrderLoading(true);
    setDirectOrderError('');
    setDirectOrderSuccess(null);
    try {
      const { data } = await api.post(`/storefront/${storeId}/orders`, {
        customer_phone: customerPhone.trim(),
        customer_name: customerName.trim() || undefined,
        items: normalizedItems,
        coupon_codes: couponCode.trim() ? [couponCode.trim()] : [],
        country_code: store?.country || undefined,
      });
      setDirectOrderSuccess(data);
    } catch (err) {
      setDirectOrderError(err?.response?.data?.detail || 'Impossible de créer la commande.');
    } finally {
      setDirectOrderLoading(false);
    }
  };

  const channels = [
    { id: 'whatsapp', label: 'WhatsApp', icon: '💬', enabled: !!store?.whatsapp_phone },
    { id: 'messenger', label: 'Messenger', icon: '💭', enabled: !!store?.messenger_page_id },
    { id: 'instagram', label: 'Instagram', icon: '📷', enabled: !!store?.instagram_handle },
    { id: 'tiktok', label: 'TikTok', icon: '🎵', enabled: !!store?.tiktok_handle },
  ].filter((c) => c.enabled);

  const panel = (
    <div className={`bg-white shadow-2xl ${fullPage ? 'rounded-2xl border border-gray-200 max-w-3xl mx-auto' : 'rounded-2xl max-w-md w-full max-h-[90vh] overflow-y-auto'}`}>
      <div className={`sticky top-0 bg-gray-900 text-white p-4 flex justify-between items-center ${fullPage ? 'rounded-t-2xl' : 'rounded-t-2xl'}`}>
        <div>
          <h2 className="text-lg font-bold">Votre panier</h2>
          {!!store?.name && <p className="text-xs text-gray-300 mt-1">{store.name}</p>}
        </div>
        {fullPage ? (
          <a href={`/store/${storeId}`} className="text-sm font-medium text-gray-200 hover:text-white">Continuer les achats</a>
        ) : (
          <button onClick={() => setIsOpen(false)} className="text-2xl">✕</button>
        )}
      </div>

      <div className="p-4 space-y-4">
              <div className="space-y-3 max-h-48 overflow-y-auto">
                {effectiveItems.map((item, idx) => (
                  <div key={`${item.product_id || item.name}-${idx}`} className="flex justify-between items-start pb-3 border-b border-gray-100">
                    <div className="flex-1">
                      <p className="font-semibold text-gray-900 text-sm">{item.name}</p>
                      <p className="text-xs text-gray-600">x{item.qty || item.quantity || 1}</p>
                    </div>
                    <p className="font-bold text-gray-900">{money(Number(item.unit_price || 0) * Number(item.qty || item.quantity || 1))}</p>
                  </div>
                ))}
              </div>

              <div className="bg-gray-100 rounded-lg p-3 space-y-2">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-gray-600">Sous-total</span>
                  <span className="font-semibold text-gray-900">{money(baseTotal)}</span>
                </div>
                {effectiveDiscount > 0 && (
                  <div className="flex justify-between items-center text-sm">
                    <span className="text-green-700">Remise</span>
                    <span className="font-semibold text-green-700">-{money(effectiveDiscount)}</span>
                  </div>
                )}
                <div className="flex justify-between items-center border-t border-gray-200 pt-2">
                  <span className="font-semibold text-gray-900">Total</span>
                  <span className="text-xl font-bold text-gray-900">{money(effectiveTotal)}</span>
                </div>
              </div>

              <div className="space-y-3 border-t border-gray-200 pt-4">
                <input
                  type="text"
                  placeholder="Votre nom"
                  value={customerName}
                  onChange={(e) => setCustomerName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                />
                <input
                  type="tel"
                  placeholder="Votre téléphone"
                  value={customerPhone}
                  onChange={(e) => setCustomerPhone(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                />
              </div>

              <div className="space-y-2 border-t border-gray-200 pt-4">
                <p className="text-xs font-semibold text-gray-600">Code promo</p>
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="PROMO2026"
                    value={couponCode}
                    onChange={(e) => setCouponCode(e.target.value.toUpperCase())}
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                  />
                  <button
                    type="button"
                    onClick={applyCouponPreview}
                    disabled={loadingPreview}
                    className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-semibold hover:bg-indigo-700 disabled:opacity-60"
                  >
                    {loadingPreview ? '...' : 'Appliquer'}
                  </button>
                </div>
                {previewError && <p className="text-xs text-red-600">{previewError}</p>}
                {!!preview?.applied_promotions?.length && (
                  <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-sm">
                    {preview.applied_promotions.map((promo) => (
                      <div key={`${promo.promotion_id}-${promo.coupon_code || 'auto'}`} className="flex justify-between gap-3 text-green-800">
                        <span>{promo.promotion_name}</span>
                        <span>{Number(promo.discount_amount || 0).toFixed(3) === '0.000' ? 'appliquée' : `-${money(promo.discount_amount)}`}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-2 border-t border-gray-200 pt-4">
                <p className="text-xs font-semibold text-gray-600 mb-2">Envoyer la commande via :</p>
                {channels.map((channel) => {
                  const url = buildContactUrl(channel.id);
                  if (!url) return null;
                  return (
                    <a
                      key={channel.id}
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center justify-center gap-2 w-full py-3 rounded-lg font-semibold text-sm transition-all hover:opacity-90 active:scale-95"
                      style={{
                        backgroundColor: channel.id === 'whatsapp' ? '#25D366' :
                          channel.id === 'messenger' ? '#0084FF' :
                            channel.id === 'instagram' ? '#E4405F' : '#000000',
                        color: '#fff',
                      }}
                    >
                      <span className="text-lg">{channel.icon}</span>
                      <span>{channel.label}</span>
                    </a>
                  );
                })}
                <button
                  type="button"
                  onClick={submitDirectOrder}
                  disabled={directOrderLoading || !!directOrderSuccess}
                  className="flex items-center justify-center gap-2 w-full py-3 rounded-lg bg-indigo-600 text-white font-semibold text-sm transition-all hover:bg-indigo-700 disabled:opacity-60"
                >
                  <span className="text-lg">✅</span>
                  <span>{directOrderLoading ? 'Création en cours...' : directOrderSuccess ? 'Commande reçue' : 'Envoyer la commande directement'}</span>
                </button>
                {directOrderError && <p className="text-xs text-red-600">{directOrderError}</p>}
                {directOrderSuccess && (
                  <p className="rounded-lg bg-green-50 border border-green-200 p-3 text-sm text-green-800">
                    Commande #{directOrderSuccess.id} enregistrée. Nous vous contacterons pour confirmer la livraison.
                  </p>
                )}
              </div>
      </div>
    </div>
  );

  if (fullPage) {
    return panel;
  }

  return (
    <>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="fixed bottom-6 left-6 z-40 w-16 h-16 rounded-full shadow-lg hover:shadow-xl transition-all active:scale-95 flex items-center justify-center text-2xl font-bold"
        style={{ backgroundColor: '#111827', color: '#fff' }}
      >
        🛒
        <span className="absolute -top-2 -right-2 bg-red-500 text-white text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center">
          {items.reduce((sum, item) => sum + (item.quantity || 1), 0)}
        </span>
      </button>

      {isOpen && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-4">
          {panel}
        </div>
      )}
    </>
  );
}
