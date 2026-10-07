const { AuthError } = require('../services/authService');
const { ProductError } = require('../services/productService');
const { CartError } = require('../services/cartService');
const { OrderError } = require('../services/orderService');

const KNOWN_ERRORS = [AuthError, ProductError, CartError, OrderError];

// Centralized so controllers just throw domain errors and never touch
// res.status() themselves — a KNOWN_ERRORS instance is a validated business
// rule violation (400), anything else is an unexpected bug (500, logged).
module.exports = function errorHandler(err, req, res, next) {
  if (KNOWN_ERRORS.some(ErrorClass => err instanceof ErrorClass)) {
    return res.status(400).json({ error: err.message });
  }
  console.error(err);
  res.status(500).json({ error: 'Internal server error.' });
};
