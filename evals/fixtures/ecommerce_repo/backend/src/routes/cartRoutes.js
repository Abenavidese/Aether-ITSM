const { Router } = require('express');
const { requireAuth } = require('../middleware/auth');
const controller = require('../controllers/cartController');

const router = Router();
router.get('/', requireAuth, controller.get);
router.post('/add', requireAuth, controller.add);
router.post('/clear', requireAuth, controller.clear);

module.exports = router;
