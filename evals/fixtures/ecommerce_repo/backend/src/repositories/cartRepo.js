const db = require('../db');

module.exports = {
  listForUser(userId) {
    return db
      .prepare(
        `SELECT ci.id, ci.qty, p.id as product_id, p.name, p.price, p.stock
         FROM cart_items ci JOIN products p ON p.id = ci.product_id
         WHERE ci.user_id = ?`
      )
      .all(userId);
  },
  upsert(userId, productId, qty) {
    db.prepare(
      `INSERT INTO cart_items (user_id, product_id, qty) VALUES (?, ?, ?)
       ON CONFLICT (user_id, product_id) DO UPDATE SET qty = qty + excluded.qty`
    ).run(userId, productId, qty);
  },
  clear(userId) {
    db.prepare('DELETE FROM cart_items WHERE user_id = ?').run(userId);
  },
};
