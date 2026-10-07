import { useEffect, useState } from 'react';
import { api } from '../api/client';

export function OrdersPage() {
  const [orders, setOrders] = useState([]);

  useEffect(() => { api.myOrders().then(setOrders); }, []);

  return (
    <div className="page">
      <h1>Order history</h1>
      {orders.length === 0 && <p>No orders yet.</p>}
      {orders.map((o) => (
        <div key={o.id} className="card">
          <p><strong>Order #{o.id}</strong> — {o.created_at} — ${o.total.toFixed(2)} ({o.status})</p>
          <ul>
            {o.items.map((i) => (
              <li key={i.id}>{i.product_name} x{i.qty} — ${(i.unit_price * i.qty).toFixed(2)}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
