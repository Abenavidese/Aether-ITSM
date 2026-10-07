const cartRepo = require('../repositories/cartRepo');
const productRepo = require('../repositories/productRepo');

class CartError extends Error {}

module.exports = {
  CartError,

  get(userId) {
    return cartRepo.listForUser(userId);
  },

  add(userId, productId, qty) {
    const product = productRepo.findById(productId);
    if (!product) throw new CartError('Product not found.');
    if (qty < 1) throw new CartError('Quantity must be at least 1.');
    cartRepo.upsert(userId, productId, qty);
    return cartRepo.listForUser(userId);
  },

  clear(userId) {
    cartRepo.clear(userId);
    return [];
  },
};
