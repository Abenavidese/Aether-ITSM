const express = require('express');
const cors = require('cors');
const config = require('./config');
const { seed } = require('./db/seed');
const errorHandler = require('./middleware/errorHandler');

seed();

const app = express();
app.use(cors());
app.use(express.json());

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.use('/api/auth', require('./routes/authRoutes'));
app.use('/api/products', require('./routes/productRoutes'));
app.use('/api/cart', require('./routes/cartRoutes'));
app.use('/api/orders', require('./routes/orderRoutes'));

app.use(errorHandler);

app.listen(config.port, () => console.log(`core-ecommerce-api backend listening on http://localhost:${config.port}`));
