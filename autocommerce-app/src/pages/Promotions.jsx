import React, { useEffect, useState } from 'react';
import { useStore } from '../context/StoreContext';

const EMPTY_CAMPAIGN = {
  name: '',
  description: '',
  channel: 'manual',
  trigger_type: 'first_purchase',
  status: 'active',
};

const EMPTY_PROMOTION = {
  name: '',
  description: '',
  promotion_type: 'automatic',
  discount_type: 'percentage',
  discount_value: '10',
  applies_to: 'all',
  eligible_categories: '',
  country_codes: '',
  channel_codes: 'storefront',
  customer_segment: '',
  priority: '100',
  stackable: false,
  minimum_cart_amount: '',
};

const EMPTY_COUPON = {
  code: '',
  promotion_id: '',
  coupon_kind: 'multi',
  per_customer_limit: '1',
  max_redemptions: '',
  quantity: '1',
};

export default function Promotions() {
  const { api } = useStore();
  const [loading, setLoading] = useState(true);
  const [campaigns, setCampaigns] = useState([]);
  const [promotions, setPromotions] = useState([]);
  const [coupons, setCoupons] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [campaignForm, setCampaignForm] = useState(EMPTY_CAMPAIGN);
  const [promotionForm, setPromotionForm] = useState(EMPTY_PROMOTION);
  const [couponForm, setCouponForm] = useState(EMPTY_COUPON);
  const [feedback, setFeedback] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const [campaignRes, promotionRes, couponRes, recRes] = await Promise.all([
        api.get('/promotions/campaigns'),
        api.get('/promotions/'),
        api.get('/promotions/coupons'),
        api.post('/promotions/recommendations', { trigger_type: 'first_purchase', channel: 'storefront' }),
      ]);
      setCampaigns(campaignRes.data.items || []);
      setPromotions(promotionRes.data.items || []);
      setCoupons(couponRes.data.items || []);
      setRecommendations(recRes.data.items || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const submitCampaign = async (e) => {
    e.preventDefault();
    await api.post('/promotions/campaigns', campaignForm);
    setCampaignForm(EMPTY_CAMPAIGN);
    setFeedback('Campagne créée.');
    load();
  };

  const submitPromotion = async (e) => {
    e.preventDefault();
    const payload = {
      name: promotionForm.name,
      description: promotionForm.description || undefined,
      promotion_type: promotionForm.promotion_type,
      discount_type: promotionForm.discount_type,
      discount_value: promotionForm.discount_type === 'free_shipping' || promotionForm.discount_type === 'gift'
        ? undefined
        : parseFloat(promotionForm.discount_value || '0'),
      applies_to: promotionForm.applies_to,
      eligible_categories: promotionForm.eligible_categories
        ? promotionForm.eligible_categories.split(',').map((v) => v.trim()).filter(Boolean)
        : undefined,
      country_codes: promotionForm.country_codes
        ? promotionForm.country_codes.split(',').map((v) => v.trim().toUpperCase()).filter(Boolean)
        : undefined,
      channel_codes: promotionForm.channel_codes
        ? promotionForm.channel_codes.split(',').map((v) => v.trim().toLowerCase()).filter(Boolean)
        : undefined,
      customer_segment: promotionForm.customer_segment || undefined,
      priority: parseInt(promotionForm.priority || '100', 10),
      stackable: promotionForm.stackable,
      rules: promotionForm.minimum_cart_amount
        ? [{ conditions: { minimum_cart_amount: parseFloat(promotionForm.minimum_cart_amount) } }]
        : [],
    };
    await api.post('/promotions/', payload);
    setPromotionForm(EMPTY_PROMOTION);
    setFeedback('Promotion créée.');
    load();
  };

  const submitCoupon = async (e) => {
    e.preventDefault();
    const payload = {
      code: couponForm.code || undefined,
      promotion_id: couponForm.promotion_id ? parseInt(couponForm.promotion_id, 10) : undefined,
      coupon_kind: couponForm.coupon_kind,
      per_customer_limit: couponForm.per_customer_limit ? parseInt(couponForm.per_customer_limit, 10) : undefined,
      max_redemptions: couponForm.max_redemptions ? parseInt(couponForm.max_redemptions, 10) : undefined,
      quantity: parseInt(couponForm.quantity || '1', 10),
    };
    const { data } = await api.post('/promotions/coupons', payload);
    setCouponForm(EMPTY_COUPON);
    setFeedback(`Coupons générés : ${(data.codes || []).join(', ')}`);
    load();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">🎯 Promotions & Marketing</h1>
          <p className="text-sm text-gray-500 mt-1">Bloc B : campagnes, coupons, moteur de règles et smart promotions.</p>
        </div>
        <button onClick={load} className="px-4 py-2 rounded-xl bg-gray-900 text-white text-sm font-semibold hover:bg-gray-800">Actualiser</button>
      </div>

      {feedback && (
        <div className="rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          {feedback}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <form onSubmit={submitCampaign} className="premium-card p-5 shadow-sm space-y-3">
          <h2 className="font-semibold text-gray-900">Créer une campagne</h2>
          <input value={campaignForm.name} onChange={(e) => setCampaignForm({ ...campaignForm, name: e.target.value })} placeholder="Campagne anniversaire" className="w-full border rounded-xl px-3 py-2 text-sm" required />
          <input value={campaignForm.description} onChange={(e) => setCampaignForm({ ...campaignForm, description: e.target.value })} placeholder="Description" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <input value={campaignForm.channel} onChange={(e) => setCampaignForm({ ...campaignForm, channel: e.target.value })} placeholder="storefront, whatsapp..." className="w-full border rounded-xl px-3 py-2 text-sm" />
          <select value={campaignForm.trigger_type} onChange={(e) => setCampaignForm({ ...campaignForm, trigger_type: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm">
            <option value="first_purchase">Premier achat</option>
            <option value="cart_abandonment">Abandon panier</option>
            <option value="inactivity">Inactivité</option>
            <option value="birthday">Anniversaire</option>
            <option value="customer_return">Retour client</option>
            <option value="high_stock">Stock élevé</option>
          </select>
          <button className="w-full bg-indigo-600 text-white rounded-xl py-2 text-sm font-semibold hover:bg-indigo-700">Créer campagne</button>
        </form>

        <form onSubmit={submitPromotion} className="premium-card p-5 shadow-sm space-y-3">
          <h2 className="font-semibold text-gray-900">Créer une promotion</h2>
          <input value={promotionForm.name} onChange={(e) => setPromotionForm({ ...promotionForm, name: e.target.value })} placeholder="-10% nouveau client" className="w-full border rounded-xl px-3 py-2 text-sm" required />
          <input value={promotionForm.description} onChange={(e) => setPromotionForm({ ...promotionForm, description: e.target.value })} placeholder="Description" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <div className="grid grid-cols-2 gap-2">
            <select value={promotionForm.promotion_type} onChange={(e) => setPromotionForm({ ...promotionForm, promotion_type: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm">
              <option value="automatic">Automatique</option>
              <option value="coupon">Coupon</option>
              <option value="smart">Smart</option>
            </select>
            <select value={promotionForm.discount_type} onChange={(e) => setPromotionForm({ ...promotionForm, discount_type: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm">
              <option value="percentage">Pourcentage</option>
              <option value="fixed">Montant fixe</option>
              <option value="free_shipping">Livraison gratuite</option>
              <option value="gift">Cadeau</option>
            </select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input value={promotionForm.discount_value} onChange={(e) => setPromotionForm({ ...promotionForm, discount_value: e.target.value })} placeholder="Valeur remise" className="w-full border rounded-xl px-3 py-2 text-sm" />
            <input value={promotionForm.minimum_cart_amount} onChange={(e) => setPromotionForm({ ...promotionForm, minimum_cart_amount: e.target.value })} placeholder="Panier min" className="w-full border rounded-xl px-3 py-2 text-sm" />
          </div>
          <select value={promotionForm.applies_to} onChange={(e) => setPromotionForm({ ...promotionForm, applies_to: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm">
            <option value="all">Tout le panier</option>
            <option value="categories">Catégories</option>
          </select>
          <input value={promotionForm.eligible_categories} onChange={(e) => setPromotionForm({ ...promotionForm, eligible_categories: e.target.value })} placeholder="Catégories CSV" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <input value={promotionForm.country_codes} onChange={(e) => setPromotionForm({ ...promotionForm, country_codes: e.target.value })} placeholder="Pays CSV ex: FR,TN" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <input value={promotionForm.channel_codes} onChange={(e) => setPromotionForm({ ...promotionForm, channel_codes: e.target.value })} placeholder="Canaux CSV ex: storefront,whatsapp" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <input value={promotionForm.customer_segment} onChange={(e) => setPromotionForm({ ...promotionForm, customer_segment: e.target.value })} placeholder="Segment: new, loyal, hot..." className="w-full border rounded-xl px-3 py-2 text-sm" />
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={promotionForm.stackable} onChange={(e) => setPromotionForm({ ...promotionForm, stackable: e.target.checked })} />
            Cumulable
          </label>
          <button className="w-full bg-indigo-600 text-white rounded-xl py-2 text-sm font-semibold hover:bg-indigo-700">Créer promotion</button>
        </form>

        <form onSubmit={submitCoupon} className="premium-card p-5 shadow-sm space-y-3">
          <h2 className="font-semibold text-gray-900">Créer des coupons</h2>
          <select value={couponForm.promotion_id} onChange={(e) => setCouponForm({ ...couponForm, promotion_id: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm">
            <option value="">Promotion liée (optionnel)</option>
            {promotions.map((promo) => (
              <option key={promo.id} value={promo.id}>{promo.name}</option>
            ))}
          </select>
          <input value={couponForm.code} onChange={(e) => setCouponForm({ ...couponForm, code: e.target.value.toUpperCase() })} placeholder="PROMO10" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <div className="grid grid-cols-2 gap-2">
            <select value={couponForm.coupon_kind} onChange={(e) => setCouponForm({ ...couponForm, coupon_kind: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm">
              <option value="multi">Multiple</option>
              <option value="single">Unique</option>
            </select>
            <input value={couponForm.quantity} onChange={(e) => setCouponForm({ ...couponForm, quantity: e.target.value })} placeholder="Quantité" className="w-full border rounded-xl px-3 py-2 text-sm" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input value={couponForm.per_customer_limit} onChange={(e) => setCouponForm({ ...couponForm, per_customer_limit: e.target.value })} placeholder="Limite/client" className="w-full border rounded-xl px-3 py-2 text-sm" />
            <input value={couponForm.max_redemptions} onChange={(e) => setCouponForm({ ...couponForm, max_redemptions: e.target.value })} placeholder="Limite globale" className="w-full border rounded-xl px-3 py-2 text-sm" />
          </div>
          <button className="w-full bg-indigo-600 text-white rounded-xl py-2 text-sm font-semibold hover:bg-indigo-700">Générer coupon(s)</button>
        </form>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="premium-card p-5 shadow-sm">
          <h2 className="font-semibold text-gray-900 mb-4">Promotions actives</h2>
          {loading ? <p className="text-sm text-gray-400">Chargement...</p> : (
            <div className="space-y-3">
              {promotions.length === 0 ? <p className="text-sm text-gray-400">Aucune promotion.</p> : promotions.map((promo) => (
                <div key={promo.id} className="rounded-xl border border-gray-100 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="font-semibold text-gray-900">{promo.name}</p>
                      <p className="text-sm text-gray-500 mt-1">{promo.description || '—'}</p>
                    </div>
                    <span className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-700">{promo.promotion_type}</span>
                  </div>
                  <div className="mt-3 text-sm text-gray-600 grid grid-cols-2 gap-2">
                    <p>Remise: <strong>{promo.discount_type}</strong>{promo.discount_value != null ? ` (${promo.discount_value})` : ''}</p>
                    <p>Priorité: <strong>{promo.priority}</strong></p>
                    <p>Pays: <strong>{(promo.country_codes || []).join(', ') || 'Tous'}</strong></p>
                    <p>Canaux: <strong>{(promo.channel_codes || []).join(', ') || 'Tous'}</strong></p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="premium-card p-5 shadow-sm">
          <h2 className="font-semibold text-gray-900 mb-4">Smart promotions suggérées</h2>
          <div className="space-y-3">
            {recommendations.length === 0 ? <p className="text-sm text-gray-400">Aucune recommandation disponible.</p> : recommendations.map((item) => (
              <div key={item.promotion_id} className="rounded-xl border border-indigo-100 bg-indigo-50 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold text-indigo-950">{item.name}</p>
                    <p className="text-sm text-indigo-700 mt-1">{item.description || 'Promotion éligible selon le contexte client.'}</p>
                  </div>
                  <span className="text-xs px-2 py-1 rounded-full bg-white text-indigo-700 border border-indigo-200">{item.trigger_type || item.promotion_type}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-6 border-t border-gray-100 pt-4">
            <h3 className="font-semibold text-gray-900 mb-3">Coupons générés</h3>
            <div className="space-y-2 max-h-64 overflow-auto">
              {coupons.length === 0 ? <p className="text-sm text-gray-400">Aucun coupon.</p> : coupons.map((coupon) => (
                <div key={coupon.id} className="flex items-center justify-between rounded-lg border border-gray-100 px-3 py-2 text-sm">
                  <span className="font-mono font-semibold text-gray-900">{coupon.code}</span>
                  <span className="text-gray-500">{coupon.redemptions_count}/{coupon.max_redemptions || '∞'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
