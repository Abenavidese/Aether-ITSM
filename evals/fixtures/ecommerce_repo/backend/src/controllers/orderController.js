const wrap = require('../middleware/wrap');
const orderService = require('../services/orderService');

exports.checkout = wrap((req, res) => {
  res.status(201).json(orderService.checkout(req.user.sub));
});

exports.listMine = wrap((req, res) => {
  res.json(orderService.listForUser(req.user.sub));
});

exports.listAll = wrap((req, res) => {
  res.json(orderService.listAll());
});
