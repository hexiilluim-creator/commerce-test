// src/pages/Orders.jsx
import React, { useEffect, useState } from 'react';
import { useStore } from '../context/StoreContext';
import { useTranslation } from 'react-i18next';
import { formatMoney } from '../utils/currency';

const STATUS_OPTIONS = ['', 'pending', 'confirmed', 'paid', 'shipped', 'delivered', 'cancelled'];
const STATUS_COLORS = {
  pending: 'bg-yellow-100 text-yellow-700',
  confirmed: 'bg-blue-100 text-blue-700',
  paid: 'bg-green-100 text-green-700',
  shipped: 'bg-purple-100 text-purple-700',
  delivered: 'bg-emerald-100 text-emerald-700',
  cancelled: 'bg-red-100 text-red-700',
};

export default function Orders() {
  const { api } = useStore();
  const { t, i18n } = useTranslation();
  const isRTL = i18n.language === 'ar';

  const [orders, setOrders] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filterStatus, setFilterStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);

  // Traduit les labels de statut dynamiquement
  const STATUS_LABELS = {
    pending:   `⏳ ${t('orders.status.pending')}`,
    confirmed: `✅ ${t('orders.status.confirmed')}`,
    paid:      `💳 ${t('orders.status.paid')}`,
    shipped:   `🚚 ${t('orders.status.shipped')}`,
    delivered: `🏠 ${t('orders.status.delivered')}`,
    cancelled: `❌ ${t('orders.status.cancelled')}`,
  };

  const load = async () => {
    setLoading(true);
    try {
      const params = { page, limit: 20 };
      if (filterStatus) params.status = filterStatus;
      const { data } = await api.get('/orders/', { params });
      setOrders(data.items || []);
      setTotal(data.total || 0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [page, filterStatus]);

  const updateStatus = async (orderId, status) => {
    await api.patch(`/orders/${orderId}/status`, { status });
    load();
    if (selected?.id === orderId) setSelected({ ...selected, status });
  };

  const { store } = useStore();
  const dateLocale = i18n.language === 'ar' ? 'ar-SA' : i18n.language === 'en' ? 'en-GB' : (store?.locale || 'fr-TN');
  const money = (value) => formatMoney(value, store, i18n.language);

  return (
    <div className="space-y-6" dir={isRTL ? 'rtl' : 'ltr'}>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">
          {t('orders.title')} <span className="text-gray-400 text-lg">({total})</span>
        </h1>
        <select value={filterStatus} onChange={e => { setFilterStatus(e.target.value); setPage(1); }}
          className="border border-gray-200 rounded-xl px-3 py-2 text-sm focus:ring-2 focus:ring-indigo-400 outline-none" dir="ltr">
          {STATUS_OPTIONS.map(s => (
            <option key={s} value={s}>{s ? STATUS_LABELS[s] : t('orders.allStatuses')}</option>
          ))}
        </select>
      </div>

      <div className="premium-card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500 text-left">
            <tr>
              {[
                t('orders.colId'),
                t('orders.colClient'),
                t('orders.colStatus'),
                t('orders.colChannel'),
                t('orders.colTotal'),
                t('orders.colDate'),
                t('orders.colActions'),
              ].map(h => (
                <th key={h} className="px-4 py-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading ? (
              <tr><td colSpan={7} className="text-center py-8 text-gray-400">{t('common.loading')}</td></tr>
            ) : orders.length === 0 ? (
              <tr><td colSpan={7} className="text-center py-8 text-gray-400">{t('orders.empty')}</td></tr>
            ) : orders.map(order => (
              <tr key={order.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => setSelected(order)}>
                <td className="px-4 py-3 font-mono text-gray-600">#{order.id}</td>
                {/* Bug6 FIX: show client name */}
                <td className="px-4 py-3">
                  <p className="font-medium text-gray-800 text-sm">{order.delivery_name || <span className="text-gray-400 italic text-xs">—</span>}</p>
                  <p className="text-gray-400 text-xs">{order.items?.length || 0} {t('orders.items')}</p>
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-1 rounded-full text-xs font-medium ${STATUS_COLORS[order.status] || 'bg-gray-100 text-gray-600'}`}>
                    {STATUS_LABELS[order.status] || order.status}
                  </span>
                </td>
                {/* Bug7 FIX: show channel icon */}
                <td className="px-4 py-3 text-gray-500 text-xs">
                  {order.channel === 'whatsapp' && <span title="WhatsApp">💬 WA</span>}
                  {order.channel === 'instagram' && <span title="Instagram">📷 IG</span>}
                  {order.channel === 'facebook' && <span title="Facebook">👍 FB</span>}
                  {order.channel === 'storefront' && <span title="Storefront">🛍️ Web</span>}
                  {(!order.channel || order.channel === 'direct') && <span title="Direct">🌐</span>}
                </td>
                <td className="px-4 py-3 font-semibold">{money(order.total_amount)}</td>
                <td className="px-4 py-3 text-gray-400">
                  {new Date(order.created_at).toLocaleDateString(dateLocale)}
                </td>
                <td className="px-4 py-3">
                  <select value={order.status}
                    onChange={e => { e.stopPropagation(); updateStatus(order.id, e.target.value); }}
                    className="border border-gray-200 rounded-lg px-2 py-1 text-xs outline-none"
                    onClick={e => e.stopPropagation()}
                    dir="ltr"
                  >
                    {STATUS_OPTIONS.filter(Boolean).map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Pagination */}
        {total > 20 && (
          <div className="flex justify-center gap-2 p-4">
            {Array.from({ length: Math.ceil(total / 20) }, (_, i) => (
              <button key={i} onClick={() => setPage(i + 1)}
                className={`w-8 h-8 rounded-lg text-sm ${page === i + 1 ? 'bg-indigo-600 text-white' : 'bg-gray-100 hover:bg-gray-200'}`}>
                {i + 1}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Order detail modal */}
      {selected && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => setSelected(null)}>
          <div className="bg-white rounded-2xl p-6 max-w-lg w-full shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h2 className="font-bold text-gray-900">{t('orders.orderDetail')} #{selected.id}</h2>
              <button onClick={() => setSelected(null)} className="text-gray-400 hover:text-gray-600">✕</button>
            </div>
            <div className="space-y-2 text-sm">
              <p><span className="text-gray-500">{t('orders.colStatus')}:</span> <strong>{STATUS_LABELS[selected.status] || selected.status}</strong></p>
              <p><span className="text-gray-500">{t('orders.colTotal')}:</span> <strong>{money(selected.total_amount)}</strong></p>
              {selected.delivery_address && (
                <p><span className="text-gray-500">{t('orders.address')}:</span> {selected.delivery_address}</p>
              )}
              {selected.notes && (
                <p><span className="text-gray-500">{t('orders.notes')}:</span> {selected.notes}</p>
              )}
              <div className="mt-3">
                <p className="text-gray-500 mb-1">{t('orders.colItems')}:</p>
                {selected.items?.map((item, i) => (
                  <div key={i} className="flex justify-between py-1 border-b border-gray-50">
                    <span>{item.name} × {item.qty}</span>
                    <span className="font-medium">{money(item.unit_price * item.qty)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
