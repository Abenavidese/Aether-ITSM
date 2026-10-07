// Idempotent seed — safe to run every startup (see server.js): checks
// counts before inserting so restarting the server never duplicates rows.
const bcrypt = require('bcryptjs');
const db = require('./index');

function seed() {
  const userCount = db.prepare('SELECT COUNT(*) as n FROM users').get().n;
  if (userCount === 0) {
    const insertUser = db.prepare('INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)');
    insertUser.run('admin@core-ecommerce.test', bcrypt.hashSync('admin1234', 8), 'admin');
    insertUser.run('demo@core-ecommerce.test', bcrypt.hashSync('demo1234', 8), 'customer');
  }

  const categoryCount = db.prepare('SELECT COUNT(*) as n FROM categories').get().n;
  if (categoryCount === 0) {
    const insertCategory = db.prepare('INSERT INTO categories (name) VALUES (?)');
    const peripherals = insertCategory.run('Peripherals').lastInsertRowid;
    const monitors = insertCategory.run('Monitors').lastInsertRowid;
    const accessories = insertCategory.run('Accessories').lastInsertRowid;

    const insertProduct = db.prepare(
      'INSERT INTO products (category_id, sku, name, price, stock) VALUES (?, ?, ?, ?, ?)'
    );
    insertProduct.run(peripherals, 'KB-001', 'Mechanical Keyboard', 79.99, 12);
    insertProduct.run(peripherals, 'MS-001', 'Wireless Mouse', 24.5, 30);
    insertProduct.run(monitors, 'MN-001', '27" Monitor', 219.0, 5);
    insertProduct.run(accessories, 'DK-001', 'USB-C Dock', 45.0, 8);
    insertProduct.run(accessories, 'WC-001', 'Webcam 1080p', 39.99, 0);
  }
}

module.exports = { seed };

if (require.main === module) {
  seed();
  console.log('Seed complete.');
}
