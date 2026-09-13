import { useState } from 'react';
import { Mail, ArrowRight, ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

export function ForgotPasswordForm() {
  const [email, setEmail] = useState('');
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    // Simulate API call for password reset
    setTimeout(() => {
      setSuccess(true);
      setLoading(false);
    }, 1500);
  };

  if (success) {
    return (
      <div className="text-center animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="w-16 h-16 bg-emerald-500/10 rounded-full flex items-center justify-center mx-auto mb-6">
          <Mail className="text-emerald-400" size={32} />
        </div>
        <h2 className="text-2xl font-semibold text-white mb-3">Check your email</h2>
        <p className="text-slate-400 text-sm mb-8">
          We've sent password reset instructions to <span className="text-slate-300 font-medium">{email}</span>.
        </p>
        <Link 
          to="/login"
          className="w-full bg-slate-800 hover:bg-slate-700 text-white font-semibold py-3.5 rounded-xl transition-all flex items-center justify-center gap-2"
        >
          <ArrowLeft size={18} /> Back to Sign In
        </Link>
      </div>
    );
  }

  return (
    <>
      <div className="mb-10 text-left">
        <h2 className="text-3xl font-semibold text-white mb-2">Reset Password</h2>
        <p className="text-slate-400 text-sm">Enter your work email address and we'll send you a link to reset your password.</p>
      </div>

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
        
        <button 
          type="submit" 
          disabled={loading || !email}
          className="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3.5 rounded-xl transition-all flex items-center justify-center gap-2 mt-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-[0_0_15px_rgba(79,70,229,0.3)] hover:shadow-[0_0_25px_rgba(79,70,229,0.5)] active:scale-[0.98]"
        >
          {loading ? 'Sending link...' : 'Send Reset Link'}
          {!loading && <ArrowRight size={18} />}
        </button>
      </form>

      <div className="mt-8 text-center">
        <p className="text-sm text-slate-400">
          Remember your password?{' '}
          <Link to="/login" className="text-indigo-400 hover:text-indigo-300 font-medium transition-colors">
            Sign in
          </Link>
        </p>
      </div>
    </>
  );
}
