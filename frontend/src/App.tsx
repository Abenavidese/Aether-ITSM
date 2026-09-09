import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { EmployeePortal } from './pages/EmployeePortal';
import { AdminDashboard } from './pages/AdminDashboard';
import { LayoutDashboard, MessageSquare } from 'lucide-react';

function Navigation() {
  const location = useLocation();
  
  return (
    <nav className="fixed top-0 left-0 h-screen w-16 bg-slate-900 border-r border-slate-800 flex flex-col items-center py-8 gap-8 z-50">
      <Link to="/" className={`p-3 rounded-xl transition-all ${location.pathname === '/' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-500/20' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'}`} title="Employee Chat">
        <MessageSquare size={24} />
      </Link>
      <Link to="/admin" className={`p-3 rounded-xl transition-all ${location.pathname === '/admin' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-500/20' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'}`} title="IT Admin">
        <LayoutDashboard size={24} />
      </Link>
    </nav>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-[#0f172a] text-slate-100 font-sans pl-16">
        <Navigation />
        <main className="p-8">
          <Routes>
            <Route path="/" element={<EmployeePortal />} />
            <Route path="/admin" element={<AdminDashboard />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
