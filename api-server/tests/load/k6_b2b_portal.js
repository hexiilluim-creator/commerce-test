import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 10,
  duration: '30s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<800'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000/api/v1';
const COOKIE = __ENV.AUTH_COOKIE || '';

export default function () {
  const params = {
    headers: {
      'Content-Type': 'application/json',
      Cookie: COOKIE,
    },
  };

  const quotePayload = JSON.stringify({
    company_account_id: 1,
    product_id: 1,
    qty: 4,
    base_unit_price: 100,
  });
  const quoteRes = http.post(`${BASE_URL}/b2b/pricing/quote`, quotePayload, params);
  check(quoteRes, {
    'quote status is 200': (r) => r.status === 200,
  });

  const dashboardRes = http.get(`${BASE_URL}/b2b/dashboard`, params);
  check(dashboardRes, {
    'dashboard status is 200': (r) => r.status === 200,
  });

  sleep(1);
}
