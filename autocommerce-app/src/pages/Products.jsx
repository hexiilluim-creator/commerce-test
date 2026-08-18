// src/pages/Products.jsx
import React, { useEffect, useState, useRef } from 'react';
import { useStore } from '../context/StoreContext';
import { useConfirm } from '../context/ConfirmContext';
import { useTranslation } from 'react-i18next';
import { formatMoney } from '../utils/currency';
import ProductImageUploader from '../components/ProductImageUploader';

export default function Products() {
  const { api, store } = useStore();
  const confirm = useConfirm();
  const { t, i18n } = useTranslation();
  const isRTL = i18n.language === 'ar';
  const money = (value) => formatMoney(value, store, i18n.language);

  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editingProduct, setEditingProduct] = useState(null);  // Bug5: edit state
  const [visionResult, setVisionResult] = useState(null);
  const [visionLoading, setVisionLoading] = useState(false);
  const [form, setForm] = useState({ name: '', description: '', price: '', stock_qty: '', category: '', image_url: '' });
  const [selectedProductForImages, setSelectedProductForImages] = useState(null);
  const [quotaPerPlan, setQuotaPerPlan] = useState(3);
  const fileRef = useRef();

  const load = async () => {
    try {
      const { data } = await api.get('/products/');
      setProducts(data.items || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleAdd = async (e) => {
    e.preventDefault();
    await api.post('/products/', { ...form, price: parseFloat(form.price), stock_qty: parseInt(form.stock_qty) });
    setShowAdd(false);
    setForm({ name: '', description: '', price: '', stock_qty: '', category: '', image_url: '' });
    load();
  };

  const handleDelete = async (id) => {
    if (!(await confirm(t('products.confirmDelete')))) return;
    const previousProducts = products;
    setProducts(prev => prev.filter((product) => product.id !== id));
    try {
      await api.delete(`/products/${id}/`);
    } catch (err) {
      setProducts(previousProducts);
      throw err;
    }
  };

  // Bug5 FIX: Edit product inline
  const handleEdit = (p) => {
    setEditingProduct(p);
    setForm({ name: p.name, description: p.description || '', price: String(p.price), stock_qty: String(p.stock_qty), category: p.category || '', image_url: p.image_url || '' });
    setShowAdd(true);
  };

  // V19.2: Récupérer le quota d'images du plan
  const fetchPlanQuota = async () => {
    try {
      const { data } = await api.get('/billing/subscription-overview');
      const maxImages = data.plan?.features?.max_product_images_per_product || 3;
      setQuotaPerPlan(maxImages);
    } catch (err) {
      console.error('Failed to fetch plan quota:', err);
      setQuotaPerPlan(3); // Default fallback
    }
  };

  useEffect(() => {
    fetchPlanQuota();
  }, []);

  const handleUpdate = async (e) => {
    e.preventDefault();
    await api.patch(`/products/${editingProduct.id}/`, {
      ...form, price: parseFloat(form.price), stock_qty: parseInt(form.stock_qty)
    });
    setShowAdd(false);
    setEditingProduct(null);
    setForm({ name: '', description: '', price: '', stock_qty: '', category: '', image_url: '' });
    load();
  };

  const handleAddOrUpdate = editingProduct ? handleUpdate : handleAdd;

  const handleVisionTest = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setVisionLoading(true);
    setVisionResult(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const { data } = await api.post('/ai/vision/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      setVisionResult(data);
    } catch (err) {
      setVisionResult({ error: err.response?.data?.detail || t('products.visionError') });
    } finally {
      setVisionLoading(false);
    }
  };

  const FIELDS = [
    ['name',      t('products.fieldName'),     'text',   true],
    ['price',     t('products.fieldPrice'),    'number', true],
    ['stock_qty', t('products.fieldStock'),    'number', true],
    ['category',  t('products.fieldCategory'), 'text',   false],
    ['image_url', t('products.fieldImageUrl'), 'text',   false],
  ];

  const TABLE_HEADERS = [
    t('products.colProduct'),
    t('products.colCategory'),
    t('products.colPrice'),
    t('products.colStock'),
    t('products.colEmbedding'),
    t('products.colActions'),
  ];

  return (
    <div className="space-y-6" dir={isRTL ? 'rtl' : 'ltr'}>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">{t('products.title')}</h1>
        <button onClick={() => setShowAdd(!showAdd)} className="bg-indigo-600 text-white px-4 py-2 rounded-xl hover:bg-indigo-700 text-sm font-medium">
          + {t('products.add')}
        </button>
      </div>

      {/* Vision AI Test Panel */}
      <div className="bg-gradient-to-r from-purple-50 to-indigo-50 rounded-2xl p-6 border border-purple-100">
        <h2 className="font-semibold text-purple-900 mb-2">🤖 {t('products.visionTitle')}</h2>
        <p className="text-sm text-purple-600 mb-4">{t('products.visionDesc')}</p>
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleVisionTest} />
        <button onClick={() => fileRef.current?.click()} disabled={visionLoading}
          className="bg-purple-600 text-white px-4 py-2 rounded-xl text-sm hover:bg-purple-700 disabled:opacity-60">
          {visionLoading ? `🔍 ${t('products.visionAnalyzing')}` : `📷 ${t('products.visionChoose')}`}
        </button>

        {visionResult && (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Vision Analysis */}
            <div className="bg-white rounded-xl p-4">
              <h3 className="font-medium text-gray-700 mb-2">🔬 {t('products.visionAnalysis')}</h3>
              {visionResult.vision_analysis ? (
                <div className="space-y-1 text-sm">
                  {Object.entries(visionResult.vision_analysis)
                    .filter(([k]) => !['raw_tokens', 'error'].includes(k))
                    .map(([k, v]) => v && (
                      <div key={k} className="flex gap-2">
                        <span className="text-gray-500 w-28 shrink-0">{k}:</span>
                        <span className="text-gray-900 font-medium">{Array.isArray(v) ? v.join(', ') : String(v)}</span>
                      </div>
                    ))}
                </div>
              ) : <p className="text-red-500 text-sm">{visionResult.error}</p>}
            </div>

            {/* Stock Match */}
            {visionResult.stock_match && (
              <div className="bg-white rounded-xl p-4">
                <h3 className="font-medium text-gray-700 mb-2">📦 {t('products.stockMatch')}</h3>
                {visionResult.stock_match.found ? (
                  <div className="space-y-1 text-sm">
                    <p className="font-semibold text-green-700">✅ {t('products.productFound')}</p>
                    <p><span className="text-gray-500">{t('products.fieldName')}:</span> <strong>{visionResult.stock_match.name}</strong></p>
                    <p><span className="text-gray-500">{t('products.fieldPrice')}:</span> <strong>{money(visionResult.stock_match.price)}</strong></p>
                    <p><span className="text-gray-500">{t('products.fieldStock')}:</span> <strong>{visionResult.stock_match.stock}</strong></p>
                    <p><span className="text-gray-500">Score:</span> <strong>{(visionResult.stock_match.match_score * 100).toFixed(0)}%</strong></p>
                  </div>
                ) : <p className="text-red-500 text-sm">❌ {t('products.noMatch')}</p>}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Product Image Uploader Modal */}
      {selectedProductForImages && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.5)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
        }}>
          <div style={{
            background: 'white',
            borderRadius: '16px',
            padding: '24px',
            maxWidth: '600px',
            width: '90%',
            maxHeight: '80vh',
            overflowY: 'auto',
          }}>
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '20px',
            }}>
              <h2 style={{
                fontSize: '18px',
                fontWeight: '700',
                color: '#0c0c0c',
                margin: 0,
              }}>
                Photos : {selectedProductForImages.name}
              </h2>
              <button
                onClick={() => setSelectedProductForImages(null)}
                style={{
                  background: 'none',
                  border: 'none',
                  fontSize: '24px',
                  cursor: 'pointer',
                }}
              >
                ✕
              </button>
            </div>
            <ProductImageUploader
              productId={selectedProductForImages.id}
              quota={quotaPerPlan}
              onImagesUpdate={() => load()}
            />
          </div>
        </div>
      )}

      {/* Add product form */}
      {showAdd && (
        <form onSubmit={handleAddOrUpdate} className="bg-white rounded-2xl p-6 shadow-sm border border-gray-100 grid grid-cols-2 gap-4">
          <h2 className="col-span-2 font-semibold text-gray-900">{editingProduct ? (t('common.edit') || 'Modifier le produit') : t('products.newProduct')}</h2>
          {FIELDS.map(([key, label, type, req]) => (
            <div key={key}>
              <label className="block text-sm text-gray-600 mb-1">{label}</label>
              <input type={type} required={req} value={form[key]} onChange={e => setForm({ ...form, [key]: e.target.value })}
                className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-400 outline-none"
                dir={['price', 'stock_qty'].includes(key) ? 'ltr' : undefined}
              />
            </div>
          ))}
          <div className="col-span-2">
            <label className="block text-sm text-gray-600 mb-1">{t('products.fieldDescription')}</label>
            <textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} rows={2}
              className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-400 outline-none" />
          </div>
          <div className="col-span-2 flex gap-3">
            <button type="submit" className="bg-indigo-600 text-white px-6 py-2 rounded-xl text-sm hover:bg-indigo-700">{t('common.save')}</button>
            <button type="button" onClick={() => { setShowAdd(false); setEditingProduct(null); setForm({ name: '', description: '', price: '', stock_qty: '', category: '', image_url: '' }); }} className="text-gray-500 px-4 py-2 rounded-xl text-sm hover:bg-gray-100">{t('common.cancel')}</button>
          </div>
        </form>
      )}

      {/* Products table */}
      <div className="premium-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500 text-left">
            <tr>
              {TABLE_HEADERS.map(h => (
                <th key={h} className="px-4 py-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading ? (
              <tr><td colSpan={6} className="text-center py-8 text-gray-400">{t('common.loading')}</td></tr>
            ) : products.length === 0 ? (
              <tr><td colSpan={6} className="text-center py-8 text-gray-400">{t('products.empty')}</td></tr>
            ) : products.map(p => (
              <tr key={p.id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <p className="font-medium text-gray-900">{p.name}</p>
                  {p.description && <p className="text-gray-400 text-xs truncate max-w-xs">{p.description}</p>}
                </td>
                <td className="px-4 py-3 text-gray-500">{p.category || '—'}</td>
                <td className="px-4 py-3 font-semibold text-gray-900">{money(p.price)}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-1 rounded-full text-xs font-medium ${p.stock_qty > 0 ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                    {p.stock_qty}
                  </span>
                </td>
                <td className="px-4 py-3">{p.has_embedding ? '✅' : '⏳'}</td>
                <td className="px-4 py-3 flex gap-2">
                  <button onClick={() => handleEdit(p)} className="text-indigo-500 hover:text-indigo-700 text-xs">{t('common.edit') || 'Modifier'}</button>
                  <button onClick={() => setSelectedProductForImages(p)} className="text-blue-500 hover:text-blue-700 text-xs">🖼️ Photos</button>
                  <button onClick={() => handleDelete(p.id)} className="text-red-400 hover:text-red-600 text-xs">{t('common.delete')}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
