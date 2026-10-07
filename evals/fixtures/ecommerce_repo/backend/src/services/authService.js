const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const config = require('../config');
const userRepo = require('../repositories/userRepo');

class AuthError extends Error {}

function issueToken(user) {
  return jwt.sign({ sub: user.id, email: user.email, role: user.role }, config.jwtSecret, { expiresIn: '4h' });
}

module.exports = {
  AuthError,

  register(email, password) {
    if (!email || !password || password.length < 6) {
      throw new AuthError('Email and a password of at least 6 characters are required.');
    }
    if (userRepo.findByEmail(email)) {
      throw new AuthError('Email already registered.');
    }
    const user = userRepo.create(email, bcrypt.hashSync(password, 8), 'customer');
    return { token: issueToken(user), user: { id: user.id, email: user.email, role: user.role } };
  },

  login(email, password) {
    const user = userRepo.findByEmail(email);
    if (!user || !bcrypt.compareSync(password, user.password_hash)) {
      throw new AuthError('Invalid credentials.');
    }
    return { token: issueToken(user), user: { id: user.id, email: user.email, role: user.role } };
  },
};
