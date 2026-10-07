const { Router } = require('express');
const { requireAuth, requireAdmin } = require('../middleware/auth');
const controller = require('../controllers/productController');

const router = Router();
router.get('/', requireAuth, controller.list);
router.get('/categories', requireAuth, controller.listCategories);
router.patch('/:id/stock', requireAuth, requireAdmin, controller.adjustStock);

module.exports = router;
