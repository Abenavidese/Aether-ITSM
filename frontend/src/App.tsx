import { BrowserRouter, Routes, Route, Link, useLocation, Navigate } from 'react-router-dom';
import { EmployeePortal } from './pages/EmployeePortal';
import { AdminDashboard } from './pages/AdminDashboard';
import { Login } from './pages/Login';
import { AuthProvider, useAuth } from './context/AuthContext';
import { LayoutDashboard, MessageSquare, LogOut } from 'lucide-react';

function Navigation() {
  const location = useLocation();
  const { logout } = useAuth();
  
  return (
    <nav className="fixed top-0 left-0 h-screen w-16 bg-slate-900 border-r border-slate-800 flex flex-col items-center py-8 z-50">
      <div className="flex flex-col gap-8 flex-1">
        <Link to="/" className={`p-3 rounded-xl transition-all ${location.pathname === '/' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-500/20' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'}`} title="Employee Chat">
          <MessageSquare size={24} />
        </Link>
        <Link to="/admin" className={`p-3 rounded-xl transition-all ${location.pathname === '/admin' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-500/20' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'}`} title="IT Admin">
          <LayoutDashboard size={24} />
        </Link>
      </div>
      <button onClick={logout} className="p-3 text-slate-500 hover:text-rose-400 hover:bg-slate-800 rounded-xl transition-all" title="Logout">
        <LogOut size={24} />
      </button>
    </nav>
  );
}

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return (
    <div className="min-h-screen bg-[#0f172a] text-slate-100 font-sans pl-16">
      <Navigation />
      <main className="p-8">
        {children}
      </main>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={
            <ProtectedRoute>
              <EmployeePortal />
            </ProtectedRoute>
          } />
          <Route path="/admin" element={
            <ProtectedRoute>
              <AdminDashboard />
            </ProtectedRoute>
          } />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
