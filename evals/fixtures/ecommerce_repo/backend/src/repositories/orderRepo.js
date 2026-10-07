const db = require('../db');

module.exports = {
  create(userId, total) {
    const result = db
      .prepare('INSERT INTO orders (user_id, total) VALUES (?, ?)')
      .run(userId, total);
    return result.lastInsertRowid;
  },
  addItem(orderId, productId, productName, qty, unitPrice) {
    db.prepare(
      'INSERT INTO order_items (order_id, product_id, product_name, qty, unit_price) VALUES (?, ?, ?, ?, ?)'
    ).run(orderId, productId, productName, qty, unitPrice);
  },
  findById(orderId) {
    const order = db.prepare('SELECT * FROM orders WHERE id = ?').get(orderId);
    if (!order) return null;
    order.items = db.prepare('SELECT * FROM order_items WHERE order_id = ?').all(orderId);
    return order;
  },
  listForUser(userId) {
    const orders = db.prepare('SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC').all(userId);
    return orders.map(o => ({ ...o, items: db.prepare('SELECT * FROM order_items WHERE order_id = ?').all(o.id) }));
  },
  listAll() {
    const orders = db
      .prepare(
        `SELECT o.*, u.email as user_email FROM orders o JOIN users u ON u.id = o.user_id ORDER BY o.id DESC`
      )
      .all();
    return orders.map(o => ({ ...o, items: db.prepare('SELECT * FROM order_items WHERE order_id = ?').all(o.id) }));
  },
};
