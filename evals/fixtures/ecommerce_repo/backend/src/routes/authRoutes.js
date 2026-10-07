const { Router } = require('express');
const { requireAuth } = require('../middleware/auth');
const controller = require('../controllers/authController');

const router = Router();
router.post('/register', controller.register);
router.post('/login', controller.login);
router.get('/me', requireAuth, controller.me);

module.exports = router;
