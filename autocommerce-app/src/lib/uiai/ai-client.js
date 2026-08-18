// autocommerce-app/src/lib/uiai/ai-client.js — typed client for Plan E.
import { api } from "../api";

export const visualBuilder = {
  generate: (payload) => api.post("/visual-builder/generate", payload),
  generateSeo: (buildId, payload) => api.put(`/visual-builder/${buildId}/seo`, payload),
  translate: (buildId, payload) => api.put(`/visual-builder/${buildId}/translations`, payload),
  submit: (buildId) => api.post(`/visual-builder/${buildId}/submit`, {}),
  review: (buildId, payload) => api.post(`/visual-builder/${buildId}/review`, payload),
  history: (buildId, limit = 100) => api.get(`/visual-builder/${buildId}/history?limit=${limit}`),
};

export const predictiveRestocking = {
  seedDemo: (sku = "DEMO-001") => api.post(`/restocking/seed-demo?sku=${encodeURIComponent(sku)}`, {}),
  forecasts: (sku, horizon = 30, limit = 200) =>
    api.get(`/restocking/forecasts?sku=${encodeURIComponent(sku)}&horizon=${horizon}&limit=${limit}`),
  seasonality: (payload) => api.post("/restocking/seasonality", payload),
  suggest: (payload) => api.post("/restocking/suggest", payload),
  approve: (id, note) => api.post(`/restocking/${id}/approve`, { note }),
  alerts: () => api.get("/restocking/alerts"),
  suggestions: () => api.get("/restocking/suggestions"),
};

export const loyaltyIA = {
  segments: () => api.get("/loyalty-ia/segments"),
  createSegment: (s) => api.post("/loyalty-ia/segments", s),
  recommend: (payload) => api.post("/loyalty-ia/recommend", payload),
  personalize: (payload) => api.post("/loyalty-ia/personalize", payload),
  churn: (payload) => api.post("/loyalty-ia/churn", payload),
  churnBulk: (payload) => api.post("/loyalty-ia/churn/bulk", payload),
  models: () => api.get("/loyalty-ia/models"),
  registerModel: (m) => api.post("/loyalty-ia/models", m),
  promote: (id) => api.post(`/loyalty-ia/models/${id}/promote`, {}),
};
