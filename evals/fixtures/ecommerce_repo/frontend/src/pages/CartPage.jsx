import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

export function CartPage() {
  const [cart, setCart] = useState([]);
  const [error, setError] = useState('');
  const [invoice, setInvoice] = useState(null);
  const navigate = useNavigate();

  useEffect(() => { api.getCart().then(setCart); }, []);

  const total = cart.reduce((sum, item) => sum + item.price * item.qty, 0);

  const handleCheckout = async () => {
    setError('');
    try {
      const order = await api.checkout();
      setInvoice(order);
      setCart([]);
    } catch (err) {
      setError(err.message);
    }
  };

  if (invoice) {
    return (
      <div className="page">
        <h1>Order confirmed</h1>
        <div className="card">
          <p>Order #{invoice.id} — total ${invoice.total.toFixed(2)}</p>
          <ul>
            {invoice.items.map((i) => (
              <li key={i.id}>{i.product_name} x{i.qty} — ${(i.unit_price * i.qty).toFixed(2)}</li>
            ))}
          </ul>
          <button onClick={() => navigate('/orders')}>View order history</button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <h1>Cart</h1>
      {error && <div className="error">{error}</div>}
      {cart.length === 0 ? (
        <p>Your cart is empty.</p>
      ) : (
        <>
          <ul className="cart-list">
            {cart.map((item) => (
              <li key={item.id}>
                <span>{item.name} x{item.qty}</span>
                <span>${(item.price * item.qty).toFixed(2)}</span>
              </li>
            ))}
          </ul>
          <p className="total">Total: ${total.toFixed(2)}</p>
          <button onClick={handleCheckout}>Facturar y comprar</button>
        </>
      )}
    </div>
  );
}
