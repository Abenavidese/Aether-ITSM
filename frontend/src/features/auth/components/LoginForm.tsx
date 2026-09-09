import { useState } from 'react';
import { useAuth } from '../../../context/AuthContext';
import { config } from '../../../config';
import { Mail, ArrowRight, Eye, EyeOff, LockKeyhole } from 'lucide-react';
import { Link } from 'react-router-dom';

export function LoginForm() {
  const [email, setEmail] = useState('admin@manitas.com');
  const [password, setPassword] = useState('password123');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const response = await fetch(`${config.API_BASE_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });

      if (!response.ok) {
        throw new Error('Invalid credentials');
      }

      const data = await response.json();
      login(data.access_token);
    } catch (err: any) {
      setError(err.message || 'Failed to login');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="mb-10 text-left">
        <h2 className="text-3xl font-semibold text-white mb-2">Welcome back</h2>
        <p className="text-slate-400 text-sm">Please enter your enterprise credentials to access your tenant dashboard.</p>
      </div>

      {error && (
        <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 p-4 rounded-xl text-sm mb-6 flex items-center gap-3">
          <div className="w-1.5 h-1.5 bg-rose-500 rounded-full animate-pulse" />
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-300 flex justify-between">
            Email
          </label>
          <div className="relative group">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <Mail className="text-slate-500 group-focus-within:text-indigo-400 transition-colors" size={18} />
            </div>
            <input 
              type="email" 
              value={email}
              onChange={e => setEmail(e.target.value)}
              className="w-full bg-slate-900/50 border border-slate-700 rounded-xl pl-11 pr-4 py-3.5 text-slate-100 placeholder-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all shadow-inner"
              placeholder="name@company.com"
              required
            />
          </div>
        </div>
        
        <div className="space-y-2">
          <div className="flex justify-between items-center">
            <label className="text-sm font-medium text-slate-300">
              Password
            </label>
            <a href="#" className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors font-medium">
              Forgot password?
            </a>
          </div>
          <div className="relative group">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <LockKeyhole className="text-slate-500 group-focus-within:text-indigo-400 transition-colors" size={18} />
            </div>
            <input 
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full bg-slate-900/50 border border-slate-700 rounded-xl pl-11 pr-12 py-3.5 text-slate-100 placeholder-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all shadow-inner"
              placeholder="••••••••"
              required
            />
            <button 
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute inset-y-0 right-0 pr-4 flex items-center text-slate-500 hover:text-slate-300 transition-colors"
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
        </div>

        <button 
          type="submit" 
          disabled={loading}
          className="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3.5 rounded-xl transition-all flex items-center justify-center gap-2 mt-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-[0_0_15px_rgba(79,70,229,0.3)] hover:shadow-[0_0_25px_rgba(79,70,229,0.5)] active:scale-[0.98]"
        >
          {loading ? 'Authenticating...' : 'Sign In'}
          {!loading && <ArrowRight size={18} />}
        </button>
      </form>

      <div className="mt-8 text-center">
        <p className="text-sm text-slate-400">
          Don't have an account?{' '}
          <Link to="/register" className="text-indigo-400 hover:text-indigo-300 font-medium transition-colors">
            Register your company
          </Link>
        </p>
      </div>

      {/* Legal Footer */}
      <div className="mt-12 pt-6 border-t border-slate-800 flex flex-col items-center gap-2">
        <p className="text-xs text-slate-500">
          By signing in, you agree to our 
          <a href="#" className="text-slate-400 hover:text-indigo-400 transition-colors mx-1">Terms of Service</a> 
          and 
          <a href="#" className="text-slate-400 hover:text-indigo-400 transition-colors ml-1">Privacy Policy</a>.
        </p>
        <p className="text-xs text-slate-600">
          © {new Date().getFullYear()} Aether Systems Inc.
        </p>
      </div>
    </>
  );
}
