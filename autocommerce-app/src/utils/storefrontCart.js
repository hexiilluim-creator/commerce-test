const CART_PREFIX = 'autocommerce:storefront:cart:';
const ACTIVE_STORE_KEY = 'autocommerce:storefront:activeStore';

function isBrowser() {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

export function setActiveStorefrontStore(storeId) {
  if (!isBrowser() || !storeId) return;
  window.localStorage.setItem(ACTIVE_STORE_KEY, String(storeId));
}

export function getActiveStorefrontStore() {
  if (!isBrowser()) return null;
  return window.localStorage.getItem(ACTIVE_STORE_KEY);
}

export function getStorefrontCartKey(storeId) {
  return `${CART_PREFIX}${storeId}`;
}

export function loadStorefrontCart(storeId) {
  if (!isBrowser() || !storeId) return [];
  try {
    const raw = window.localStorage.getItem(getStorefrontCartKey(storeId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveStorefrontCart(storeId, items) {
  if (!isBrowser() || !storeId) return;
  const safeItems = Array.isArray(items) ? items : [];
  window.localStorage.setItem(getStorefrontCartKey(storeId), JSON.stringify(safeItems));
  setActiveStorefrontStore(storeId);
}

export function clearStorefrontCart(storeId) {
  if (!isBrowser() || !storeId) return;
  window.localStorage.removeItem(getStorefrontCartKey(storeId));
}
