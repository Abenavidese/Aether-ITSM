import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user) return null;

  return (
    <nav className="navbar">
      <span className="brand">Core Ecommerce</span>
      <Link to="/">Shop</Link>
      <Link to="/cart">Cart</Link>
      <Link to="/orders">Orders</Link>
      {user.role === 'admin' && <Link to="/admin">Admin</Link>}
      <span className="spacer" />
      <span className="user-email">{user.email}</span>
      <button onClick={() => { logout(); navigate('/login'); }}>Logout</button>
    </nav>
  );
}
