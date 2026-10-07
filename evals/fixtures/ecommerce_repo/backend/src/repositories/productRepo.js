const db = require('../db');

module.exports = {
  listWithCategory() {
    return db
      .prepare(
        `SELECT p.id, p.sku, p.name, p.price, p.stock, c.id as category_id, c.name as category_name
         FROM products p LEFT JOIN categories c ON c.id = p.category_id
         ORDER BY p.id`
      )
      .all();
  },
  findById(id) {
    return db.prepare('SELECT * FROM products WHERE id = ?').get(id);
  },
  updateStock(id, stock) {
    db.prepare('UPDATE products SET stock = ? WHERE id = ?').run(stock, id);
  },
  decrementStock(id, qty) {
    db.prepare('UPDATE products SET stock = stock - ? WHERE id = ?').run(qty, id);
  },
  listCategories() {
    return db.prepare('SELECT * FROM categories ORDER BY name').all();
  },
};
