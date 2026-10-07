module.exports = {
  port: process.env.PORT || 4000,
  // Test fixture — not a real secret, never used outside localhost.
  jwtSecret: process.env.JWT_SECRET || 'core-ecommerce-test-fixture-secret',
  dbPath: process.env.DB_PATH || require('path').join(__dirname, '..', 'data.sqlite'),
};
