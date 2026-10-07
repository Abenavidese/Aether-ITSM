const wrap = require('../middleware/wrap');
const productService = require('../services/productService');

exports.list = wrap((req, res) => {
  res.json(productService.list());
});

exports.listCategories = wrap((req, res) => {
  res.json(productService.listCategories());
});

exports.adjustStock = wrap((req, res) => {
  const { stock } = req.body || {};
  res.json(productService.adjustStock(Number(req.params.id), Number(stock)));
});
