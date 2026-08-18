import React, { useEffect, useMemo, useState } from 'react';
import { useStore } from '../context/StoreContext';

const EMPTY_ACCOUNT = {
  account_type: 'garage',
  name: '',
  legal_name: '',
  billing_email: '',
  phone: '',
  address: '',
  credit_limit: '',
  payment_terms_days: '30',
};

const EMPTY_RULE = {
  company_account_id: '',
  rule_type: 'discount',
  product_id: '',
  contract_code: '',
  min_qty: '1',
  negotiated_unit_price: '',
  discount_percent: '',
  rebate_percent: '',
  currency: 'EUR',
};

const EMPTY_ORDER = {
  company_account_id: '',
  po_number: '',
  internal_reference: '',
  currency: 'EUR',
  payment_terms_days: '30',
  auto_approve: false,
  items: [{ product_id: '', name: '', qty: '1' }],
};

export default function B2BPortal() {
  const { api } = useStore();
  const [loading, setLoading] = useState(true);
  const [accounts, setAccounts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [feedback, setFeedback] = useState('');
  const [accountForm, setAccountForm] = useState(EMPTY_ACCOUNT);
  const [ruleForm, setRuleForm] = useState(EMPTY_RULE);
  const [orderForm, setOrderForm] = useState(EMPTY_ORDER);
  const [quoteForm, setQuoteForm] = useState({ company_account_id: '', product_id: '', qty: '1', base_unit_price: '' });
  const [quoteResult, setQuoteResult] = useState(null);

  const selectedAccount = useMemo(
    () => accounts.find((a) => String(a.id) === String(ruleForm.company_account_id || orderForm.company_account_id || quoteForm.company_account_id)),
    [accounts, ruleForm.company_account_id, orderForm.company_account_id, quoteForm.company_account_id],
  );

  const load = async () => {
    setLoading(true);
    try {
      const [accountsRes, ordersRes, invoicesRes, dashboardRes] = await Promise.all([
        api.get('/b2b/accounts'),
        api.get('/b2b/orders'),
        api.get('/b2b/invoices'),
        api.get('/b2b/dashboard'),
      ]);
      setAccounts(accountsRes.data || []);
      setOrders(ordersRes.data || []);
      setInvoices(invoicesRes.data || []);
      setDashboard(dashboardRes.data || null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const submitAccount = async (e) => {
    e.preventDefault();
    await api.post('/b2b/accounts', {
      ...accountForm,
      credit_limit: accountForm.credit_limit ? parseFloat(accountForm.credit_limit) : undefined,
      payment_terms_days: parseInt(accountForm.payment_terms_days || '30', 10),
    });
    setFeedback('Compte entreprise créé.');
    setAccountForm(EMPTY_ACCOUNT);
    await load();
  };

  const submitRule = async (e) => {
    e.preventDefault();
    if (!ruleForm.company_account_id) return;
    await api.post(`/b2b/accounts/${ruleForm.company_account_id}/pricing`, {
      rule_type: ruleForm.rule_type,
      product_id: ruleForm.product_id ? parseInt(ruleForm.product_id, 10) : undefined,
      contract_code: ruleForm.contract_code || undefined,
      min_qty: parseInt(ruleForm.min_qty || '1', 10),
      negotiated_unit_price: ruleForm.negotiated_unit_price ? parseFloat(ruleForm.negotiated_unit_price) : undefined,
      discount_percent: ruleForm.discount_percent ? parseFloat(ruleForm.discount_percent) : undefined,
      rebate_percent: ruleForm.rebate_percent ? parseFloat(ruleForm.rebate_percent) : undefined,
      currency: ruleForm.currency,
    });
    setFeedback('Règle tarifaire enregistrée.');
    setRuleForm(EMPTY_RULE);
  };

  const submitQuote = async (e) => {
    e.preventDefault();
    const { data } = await api.post('/b2b/pricing/quote', {
      company_account_id: parseInt(quoteForm.company_account_id, 10),
      product_id: quoteForm.product_id ? parseInt(quoteForm.product_id, 10) : undefined,
      qty: parseInt(quoteForm.qty || '1', 10),
      base_unit_price: parseFloat(quoteForm.base_unit_price || '0'),
    });
    setQuoteResult(data);
  };

  const submitOrder = async (e) => {
    e.preventDefault();
    if (!orderForm.company_account_id) return;
    await api.post('/b2b/orders', {
      company_account_id: parseInt(orderForm.company_account_id, 10),
      po_number: orderForm.po_number || undefined,
      internal_reference: orderForm.internal_reference || undefined,
      currency: orderForm.currency,
      payment_terms_days: parseInt(orderForm.payment_terms_days || '30', 10),
      auto_approve: orderForm.auto_approve,
      items: orderForm.items.map((item) => ({
        product_id: item.product_id ? parseInt(item.product_id, 10) : undefined,
        name: item.name || undefined,
        qty: parseInt(item.qty || '1', 10),
      })),
    });
    setFeedback('Commande B2B créée.');
    setOrderForm(EMPTY_ORDER);
    await load();
  };

  const approveOrder = async (orderId) => {
    await api.post(`/b2b/orders/${orderId}/approve`);
    setFeedback(`Commande #${orderId} approuvée.`);
    await load();
  };

  const invoiceOrder = async (orderId, companyAccountId) => {
    await api.post('/b2b/invoices/grouped', {
      company_account_id: companyAccountId,
      order_ids: [orderId],
      payment_mode: 'deferred',
      grouped_period_label: 'Facture instantanée',
    });
    setFeedback(`Facture groupée générée pour la commande #${orderId}.`);
    await load();
  };

  const updateOrderItem = (index, patch) => {
    setOrderForm((prev) => ({
      ...prev,
      items: prev.items.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    }));
  };

  const addOrderItem = () => {
    setOrderForm((prev) => ({
      ...prev,
      items: [...prev.items, { product_id: '', name: '', qty: '1' }],
    }));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">🏭 Portail B2B</h1>
          <p className="text-sm text-gray-500 mt-1">Comptes entreprises, tarification négociée, validation interne et facturation groupée.</p>
        </div>
        <button onClick={load} className="px-4 py-2 rounded-xl bg-gray-900 text-white text-sm font-semibold hover:bg-gray-800">Actualiser</button>
      </div>

      {feedback && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          {feedback}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <MetricCard title="Comptes" value={dashboard?.accounts_total ?? '—'} />
        <MetricCard title="Commandes en attente" value={dashboard?.pending_orders ?? '—'} />
        <MetricCard title="Factures en retard" value={dashboard?.overdue_invoices ?? '—'} />
        <MetricCard title="Exposition crédit" value={dashboard?.credit_exposure != null ? `${dashboard.credit_exposure} €` : '—'} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <form onSubmit={submitAccount} className="premium-card p-5 shadow-sm space-y-3">
          <h2 className="font-semibold text-gray-900">F1 · Compte entreprise</h2>
          <select value={accountForm.account_type} onChange={(e) => setAccountForm({ ...accountForm, account_type: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm">
            <option value="garage">Garage</option>
            <option value="reseller">Revendeur</option>
            <option value="wholesaler">Grossiste</option>
          </select>
          <input value={accountForm.name} onChange={(e) => setAccountForm({ ...accountForm, name: e.target.value })} placeholder="Nom du compte" className="w-full border rounded-xl px-3 py-2 text-sm" required />
          <input value={accountForm.legal_name} onChange={(e) => setAccountForm({ ...accountForm, legal_name: e.target.value })} placeholder="Raison sociale" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <input value={accountForm.billing_email} onChange={(e) => setAccountForm({ ...accountForm, billing_email: e.target.value })} placeholder="Email facturation" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <div className="grid grid-cols-2 gap-2">
            <input value={accountForm.credit_limit} onChange={(e) => setAccountForm({ ...accountForm, credit_limit: e.target.value })} placeholder="Crédit max" className="w-full border rounded-xl px-3 py-2 text-sm" />
            <input value={accountForm.payment_terms_days} onChange={(e) => setAccountForm({ ...accountForm, payment_terms_days: e.target.value })} placeholder="Échéance (jours)" className="w-full border rounded-xl px-3 py-2 text-sm" />
          </div>
          <button className="w-full bg-indigo-600 text-white rounded-xl py-2 text-sm font-semibold hover:bg-indigo-700">Créer le compte</button>
        </form>

        <form onSubmit={submitRule} className="premium-card p-5 shadow-sm space-y-3">
          <h2 className="font-semibold text-gray-900">F2 · Tarification & contrats</h2>
          <select value={ruleForm.company_account_id} onChange={(e) => setRuleForm({ ...ruleForm, company_account_id: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm" required>
            <option value="">Compte entreprise</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>{account.name}</option>
            ))}
          </select>
          <div className="grid grid-cols-2 gap-2">
            <select value={ruleForm.rule_type} onChange={(e) => setRuleForm({ ...ruleForm, rule_type: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm">
              <option value="negotiated">Prix négocié</option>
              <option value="tiered">Tarif dégressif</option>
              <option value="discount">Remise</option>
              <option value="contract">Contrat</option>
            </select>
            <input value={ruleForm.product_id} onChange={(e) => setRuleForm({ ...ruleForm, product_id: e.target.value })} placeholder="Product ID" className="w-full border rounded-xl px-3 py-2 text-sm" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input value={ruleForm.negotiated_unit_price} onChange={(e) => setRuleForm({ ...ruleForm, negotiated_unit_price: e.target.value })} placeholder="Prix négocié" className="w-full border rounded-xl px-3 py-2 text-sm" />
            <input value={ruleForm.discount_percent} onChange={(e) => setRuleForm({ ...ruleForm, discount_percent: e.target.value })} placeholder="Remise %" className="w-full border rounded-xl px-3 py-2 text-sm" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input value={ruleForm.rebate_percent} onChange={(e) => setRuleForm({ ...ruleForm, rebate_percent: e.target.value })} placeholder="Rabais %" className="w-full border rounded-xl px-3 py-2 text-sm" />
            <input value={ruleForm.contract_code} onChange={(e) => setRuleForm({ ...ruleForm, contract_code: e.target.value })} placeholder="Code contrat" className="w-full border rounded-xl px-3 py-2 text-sm" />
          </div>
          <input value={ruleForm.min_qty} onChange={(e) => setRuleForm({ ...ruleForm, min_qty: e.target.value })} placeholder="Quantité minimale" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <button className="w-full bg-indigo-600 text-white rounded-xl py-2 text-sm font-semibold hover:bg-indigo-700">Enregistrer la règle</button>
        </form>

        <form onSubmit={submitQuote} className="premium-card p-5 shadow-sm space-y-3">
          <h2 className="font-semibold text-gray-900">F2 · Simulation de prix</h2>
          <select value={quoteForm.company_account_id} onChange={(e) => setQuoteForm({ ...quoteForm, company_account_id: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm" required>
            <option value="">Compte entreprise</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>{account.name}</option>
            ))}
          </select>
          <input value={quoteForm.product_id} onChange={(e) => setQuoteForm({ ...quoteForm, product_id: e.target.value })} placeholder="Product ID" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <div className="grid grid-cols-2 gap-2">
            <input value={quoteForm.qty} onChange={(e) => setQuoteForm({ ...quoteForm, qty: e.target.value })} placeholder="Quantité" className="w-full border rounded-xl px-3 py-2 text-sm" />
            <input value={quoteForm.base_unit_price} onChange={(e) => setQuoteForm({ ...quoteForm, base_unit_price: e.target.value })} placeholder="Prix catalogue" className="w-full border rounded-xl px-3 py-2 text-sm" />
          </div>
          <button className="w-full bg-gray-900 text-white rounded-xl py-2 text-sm font-semibold hover:bg-gray-800">Calculer</button>
          {quoteResult && (
            <div className="rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-900 space-y-1">
              <p>Prix final: <strong>{quoteResult.final_unit_price}</strong></p>
              <p>Écart: <strong>{quoteResult.discount_amount}</strong></p>
              <p>Règle: <strong>{quoteResult.applied_rule_type || 'catalogue'}</strong></p>
              <p>Explication: {quoteResult.explanation}</p>
            </div>
          )}
        </form>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <form onSubmit={submitOrder} className="premium-card p-5 shadow-sm space-y-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold text-gray-900">F3/F4 · Commande B2B</h2>
              <p className="text-sm text-gray-500 mt-1">Commande multi-utilisateurs avec PO, échéance et validation interne.</p>
            </div>
            {selectedAccount && <span className="text-xs px-3 py-1 rounded-full bg-gray-100 text-gray-700">{selectedAccount.name}</span>}
          </div>
          <select value={orderForm.company_account_id} onChange={(e) => setOrderForm({ ...orderForm, company_account_id: e.target.value })} className="w-full border rounded-xl px-3 py-2 text-sm" required>
            <option value="">Compte entreprise</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>{account.name}</option>
            ))}
          </select>
          <div className="grid grid-cols-2 gap-2">
            <input value={orderForm.po_number} onChange={(e) => setOrderForm({ ...orderForm, po_number: e.target.value })} placeholder="Bon de commande / PO" className="w-full border rounded-xl px-3 py-2 text-sm" />
            <input value={orderForm.internal_reference} onChange={(e) => setOrderForm({ ...orderForm, internal_reference: e.target.value })} placeholder="Réf interne" className="w-full border rounded-xl px-3 py-2 text-sm" />
          </div>
          <input value={orderForm.payment_terms_days} onChange={(e) => setOrderForm({ ...orderForm, payment_terms_days: e.target.value })} placeholder="Échéance (jours)" className="w-full border rounded-xl px-3 py-2 text-sm" />
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={orderForm.auto_approve} onChange={(e) => setOrderForm({ ...orderForm, auto_approve: e.target.checked })} />
            Auto-approuver la commande
          </label>
          <div className="space-y-3">
            {orderForm.items.map((item, index) => (
              <div key={index} className="grid grid-cols-3 gap-2">
                <input value={item.product_id} onChange={(e) => updateOrderItem(index, { product_id: e.target.value })} placeholder="Product ID" className="w-full border rounded-xl px-3 py-2 text-sm" />
                <input value={item.name} onChange={(e) => updateOrderItem(index, { name: e.target.value })} placeholder="Libellé" className="w-full border rounded-xl px-3 py-2 text-sm" />
                <input value={item.qty} onChange={(e) => updateOrderItem(index, { qty: e.target.value })} placeholder="Qté" className="w-full border rounded-xl px-3 py-2 text-sm" />
              </div>
            ))}
          </div>
          <button type="button" onClick={addOrderItem} className="px-3 py-2 rounded-xl border border-gray-200 text-sm font-medium text-gray-700 hover:bg-gray-50">+ Ajouter une ligne</button>
          <button className="w-full bg-indigo-600 text-white rounded-xl py-2 text-sm font-semibold hover:bg-indigo-700">Créer la commande</button>
        </form>

        <div className="premium-card p-5 shadow-sm">
          <h2 className="font-semibold text-gray-900 mb-4">F1/F3/F4 · Comptes, commandes & factures</h2>
          {loading ? <p className="text-sm text-gray-400">Chargement...</p> : (
            <div className="space-y-5">
              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-2">Comptes entreprises</h3>
                {accounts.length === 0 ? <p className="text-sm text-gray-400">Aucun compte.</p> : accounts.map((account) => (
                  <div key={account.id} className="rounded-xl border border-gray-100 p-4 mb-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-gray-900">{account.name}</p>
                        <p className="text-sm text-gray-500 mt-1">{account.account_type} · échéance {account.payment_terms_days} jours</p>
                      </div>
                      <span className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-700">{account.status}</span>
                    </div>
                  </div>
                ))}
              </div>

              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-2">Commandes B2B</h3>
                {orders.length === 0 ? <p className="text-sm text-gray-400">Aucune commande.</p> : orders.map((order) => (
                  <div key={order.id} className="rounded-xl border border-gray-100 p-4 mb-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold text-gray-900">Commande #{order.id}</p>
                        <p className="text-sm text-gray-500 mt-1">PO {order.po_number || '—'} · total {order.total_amount} {order.currency}</p>
                      </div>
                      <span className="text-xs px-2 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200">{order.approval_status}</span>
                    </div>
                    <div className="flex flex-wrap gap-2 mt-3">
                      {order.approval_status !== 'approved' && (
                        <button onClick={() => approveOrder(order.id)} className="px-3 py-2 rounded-xl bg-gray-900 text-white text-xs font-semibold hover:bg-gray-800">Approuver</button>
                      )}
                      {order.approval_status === 'approved' && !order.invoice_number && (
                        <button onClick={() => invoiceOrder(order.id, order.company_account_id)} className="px-3 py-2 rounded-xl bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700">Facturer</button>
                      )}
                      {order.invoice_number && (
                        <span className="text-xs px-2 py-1 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">{order.invoice_number}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <div>
                <h3 className="text-sm font-semibold text-gray-700 mb-2">Factures groupées</h3>
                {invoices.length === 0 ? <p className="text-sm text-gray-400">Aucune facture.</p> : invoices.map((invoice) => (
                  <div key={invoice.id} className="rounded-xl border border-gray-100 p-4 mb-3">
                    <p className="font-semibold text-gray-900">{invoice.invoice_number}</p>
                    <p className="text-sm text-gray-500 mt-1">{invoice.grouped_order_ids.length} commande(s) · total {invoice.total_amount} {invoice.currency}</p>
                    <p className="text-xs text-gray-400 mt-1">Mode {invoice.payment_mode} · échéance {invoice.due_date || '—'}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function MetricCard({ title, value }) {
  return (
    <div className="premium-card p-5 shadow-sm">
      <p className="text-sm text-gray-500">{title}</p>
      <p className="text-2xl font-bold text-gray-900 mt-2">{value}</p>
    </div>
  );
}
