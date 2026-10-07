const wrap = require('../middleware/wrap');
const authService = require('../services/authService');

exports.register = wrap((req, res) => {
  const { email, password } = req.body || {};
  res.status(201).json(authService.register(email, password));
});

exports.login = wrap((req, res) => {
  const { email, password } = req.body || {};
  res.json(authService.login(email, password));
});

exports.me = wrap((req, res) => {
  res.json({ id: req.user.sub, email: req.user.email, role: req.user.role });
});
