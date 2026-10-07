const TOKEN_KEY = 'core_ecommerce_token';
// Empty in dev (Vite proxies /api to :4000); in production, the backend's origin (e.g. https://x.onrender.com).
const API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request(path, options = {}) {
  const token = getToken();
  const res = await fetch(`${API_URL}/api${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

export const api = {
  register: (email, password) => request('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
  login: (email, password) => request('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: () => request('/auth/me'),

  listProducts: () => request('/products'),
  adjustStock: (id, stock) => request(`/products/${id}/stock`, { method: 'PATCH', body: JSON.stringify({ stock }) }),

  getCart: () => request('/cart'),
  addToCart: (product_id, qty) => request('/cart/add', { method: 'POST', body: JSON.stringify({ product_id, qty }) }),

  checkout: () => request('/orders/checkout', { method: 'POST' }),
  myOrders: () => request('/orders/mine'),
  allOrders: () => request('/orders/all'),
};
