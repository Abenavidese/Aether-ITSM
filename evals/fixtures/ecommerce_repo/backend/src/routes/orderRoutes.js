const { Router } = require('express');
const { requireAuth, requireAdmin } = require('../middleware/auth');
const controller = require('../controllers/orderController');

const router = Router();
router.post('/checkout', requireAuth, controller.checkout);
router.get('/mine', requireAuth, controller.listMine);
router.get('/all', requireAuth, requireAdmin, controller.listAll);

module.exports = router;
