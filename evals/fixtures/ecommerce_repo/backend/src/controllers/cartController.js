const wrap = require('../middleware/wrap');
const cartService = require('../services/cartService');

exports.get = wrap((req, res) => {
  res.json(cartService.get(req.user.sub));
});

exports.add = wrap((req, res) => {
  const { product_id, qty } = req.body || {};
  res.json(cartService.add(req.user.sub, Number(product_id), Number(qty) || 1));
});

exports.clear = wrap((req, res) => {
  res.json(cartService.clear(req.user.sub));
});
