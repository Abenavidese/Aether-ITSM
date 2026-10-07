import { useEffect, useState } from 'react';
import { api } from '../api/client';

export function AdminPage() {
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [stockEdits, setStockEdits] = useState({});

  const loadProducts = () => api.listProducts().then(setProducts);

  useEffect(() => {
    loadProducts();
    api.allOrders().then(setOrders);
  }, []);

  const saveStock = async (id) => {
    const value = stockEdits[id];
    if (value === undefined) return;
    await api.adjustStock(id, Number(value));
    setStockEdits((prev) => { const next = { ...prev }; delete next[id]; return next; });
    loadProducts();
  };

  return (
    <div className="page">
      <h1>Admin</h1>

      <h2>Inventory</h2>
      <table className="admin-table">
        <thead>
          <tr><th>SKU</th><th>Name</th><th>Price</th><th>Stock</th><th></th></tr>
        </thead>
        <tbody>
          {products.map((p) => (
            <tr key={p.id}>
              <td>{p.sku}</td>
              <td>{p.name}</td>
              <td>${p.price.toFixed(2)}</td>
              <td>
                <input
                  type="number"
                  value={stockEdits[p.id] ?? p.stock}
                  onChange={(e) => setStockEdits({ ...stockEdits, [p.id]: e.target.value })}
                  style={{ width: '60px' }}
                />
              </td>
              <td><button onClick={() => saveStock(p.id)}>Save</button></td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>All orders</h2>
      {orders.map((o) => (
        <div key={o.id} className="card">
          <p><strong>Order #{o.id}</strong> — {o.user_email} — {o.created_at} — ${o.total.toFixed(2)}</p>
        </div>
      ))}
    </div>
  );
}
