const productRepo = require('../repositories/productRepo');

class ProductError extends Error {}

module.exports = {
  ProductError,

  list() {
    return productRepo.listWithCategory();
  },

  listCategories() {
    return productRepo.listCategories();
  },

  adjustStock(productId, stock) {
    const product = productRepo.findById(productId);
    if (!product) throw new ProductError('Product not found.');
    if (stock < 0) throw new ProductError('Stock cannot be negative.');
    productRepo.updateStock(productId, stock);
    return productRepo.findById(productId);
  },
};
