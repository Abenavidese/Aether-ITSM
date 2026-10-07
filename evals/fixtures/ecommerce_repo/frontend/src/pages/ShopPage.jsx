import { useEffect, useState } from 'react';
import { api } from '../api/client';

export function ShopPage() {
  const [products, setProducts] = useState([]);
  const [message, setMessage] = useState('');

  const load = () => api.listProducts().then(setProducts);

  useEffect(() => { load(); }, []);

  const addToCart = async (id) => {
    setMessage('');
    try {
      await api.addToCart(id, 1);
      setMessage('Added to cart.');
      load();
    } catch (err) {
      setMessage(err.message);
    }
  };

  const byCategory = products.reduce((acc, p) => {
    const key = p.category_name || 'Uncategorized';
    (acc[key] = acc[key] || []).push(p);
    return acc;
  }, {});

  return (
    <div className="page">
      <h1>Products</h1>
      {message && <div className="banner">{message}</div>}
      {Object.entries(byCategory).map(([category, items]) => (
        <div key={category} className="category-block">
          <h2>{category}</h2>
          <div className="product-grid">
            {items.map((p) => (
              <div key={p.id} className="product-card">
                <h3>{p.name}</h3>
                <p className="sku">{p.sku}</p>
                <p className="price">${p.price.toFixed(2)}</p>
                <p className="stock">{p.stock > 0 ? `${p.stock} in stock` : 'Out of stock'}</p>
                <button disabled={p.stock === 0} onClick={() => addToCart(p.id)}>Add to cart</button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
