// Services are synchronous (better-sqlite3 has no async API), but wrapping
// every controller body in try/catch to forward thrown errors to
// errorHandler.js would be pure boilerplate — this does it once.
module.exports = fn => (req, res, next) => {
  try {
    fn(req, res, next);
  } catch (err) {
    next(err);
  }
};
