# core-ecommerce-api

Disposable test fixture — a small e-commerce app (auth with roles, product
catalog with categories, cart, checkout, order history, admin inventory
panel) used as a target repo to exercise an AI support agent (issue
creation, code search, health checks) against something with real
structure. **Not production code**: SQLite file storage, a fixed JWT
secret, no test suite.

## Structure

```
backend/    Express API, layered (routes -> controllers -> services -> repositories), SQLite (better-sqlite3), JWT auth with roles
frontend/   React + Vite SPA (react-router), talks to the backend via the Vite dev proxy
```

## Run

```bash
# Terminal 1
cd backend && npm install && npm start        # http://localhost:4000

# Terminal 2
cd frontend && npm install && npm run dev     # http://localhost:5173
```

Seed accounts (created automatically on first backend start):
- `admin@core-ecommerce.test` / `admin1234` (role: admin — inventory + all orders)
- `demo@core-ecommerce.test` / `demo1234` (role: customer)

## Flow

1. Log in (or register a new customer account).
2. Browse products by category, add to cart.
3. Cart -> "Facturar y comprar" -> checkout is atomic (stock validated and
   decremented, order recorded, cart cleared as one DB transaction).
4. Order history under "Orders".
5. Admin account additionally sees "Admin": edit stock per product, view
   every order across all customers.

## API surface

`GET /health` · `POST /api/auth/{register,login}` · `GET /api/auth/me` ·
`GET /api/products` (+`/categories`) · `PATCH /api/products/:id/stock` (admin) ·
`GET/POST /api/cart`, `/api/cart/add`, `/api/cart/clear` ·
`POST /api/orders/checkout` · `GET /api/orders/mine` · `GET /api/orders/all` (admin)
