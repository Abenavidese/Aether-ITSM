const db = require('../db');
const cartRepo = require('../repositories/cartRepo');
const orderRepo = require('../repositories/orderRepo');
const productRepo = require('../repositories/productRepo');

class OrderError extends Error {}

module.exports = {
  OrderError,

  checkout(userId) {
    const cartItems = cartRepo.listForUser(userId);
    if (cartItems.length === 0) throw new OrderError('Cart is empty.');

    for (const item of cartItems) {
      if (item.stock < item.qty) {
        throw new OrderError(`Not enough stock for "${item.name}" (requested ${item.qty}, available ${item.stock}).`);
      }
    }

    // Atomic: either every line item is applied (stock decremented, order
    // recorded) or none is — a partial checkout would leave stock and the
    // cart inconsistent with each other.
    const runCheckout = db.transaction(() => {
      const total = cartItems.reduce((sum, i) => sum + i.price * i.qty, 0);
      const orderId = orderRepo.create(userId, total);
      for (const item of cartItems) {
        orderRepo.addItem(orderId, item.product_id, item.name, item.qty, item.price);
        productRepo.decrementStock(item.product_id, item.qty);
      }
      cartRepo.clear(userId);
      return orderId;
    });

    const orderId = runCheckout();
    return orderRepo.findById(orderId);
  },

  listForUser(userId) {
    return orderRepo.listForUser(userId);
  },

  listAll() {
    return orderRepo.listAll();
  },
};
