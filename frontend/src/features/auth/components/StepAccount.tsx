import { User, Mail, LockKeyhole, Eye, EyeOff } from 'lucide-react';

interface StepAccountProps {
  fullName: string;
  email: string;
  password: string;
  confirmPassword: string;
  showPassword: boolean;
  onFieldChange: (field: string, value: string) => void;
  onTogglePassword: () => void;
}

export function StepAccount({ fullName, email, password, confirmPassword, showPassword, onFieldChange, onTogglePassword }: StepAccountProps) {
  return (
    <div className="space-y-5 animate-in fade-in slide-in-from-right-4 duration-500">
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Full Name</label>
        <div className="relative group">
          <User className="absolute left-4 top-3.5 text-slate-500 group-focus-within:text-indigo-400 transition-colors" size={18} />
          <input type="text" value={fullName} onChange={e => onFieldChange('fullName', e.target.value)} className="w-full bg-slate-900/50 border border-slate-700 rounded-xl pl-11 pr-4 py-3 text-slate-100 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all" placeholder="John Doe" />
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Work Email</label>
        <div className="relative group">
          <Mail className="absolute left-4 top-3.5 text-slate-500 group-focus-within:text-indigo-400 transition-colors" size={18} />
          <input type="email" value={email} onChange={e => onFieldChange('email', e.target.value)} className="w-full bg-slate-900/50 border border-slate-700 rounded-xl pl-11 pr-4 py-3 text-slate-100 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all" placeholder="name@company.com" />
        </div>
      </div>
      
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-300">Password</label>
          <div className="relative group">
            <LockKeyhole className="absolute left-4 top-3.5 text-slate-500 group-focus-within:text-indigo-400 transition-colors" size={18} />
            <input type={showPassword ? "text" : "password"} value={password} onChange={e => onFieldChange('password', e.target.value)} className="w-full bg-slate-900/50 border border-slate-700 rounded-xl pl-11 pr-10 py-3 text-slate-100 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all" placeholder="••••••••" />
            <button type="button" onClick={onTogglePassword} className="absolute right-3 top-3.5 text-slate-500 hover:text-slate-300">
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
        </div>
        
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-300">Confirm Password</label>
          <div className="relative group">
            <LockKeyhole className="absolute left-4 top-3.5 text-slate-500 group-focus-within:text-indigo-400 transition-colors" size={18} />
            <input type={showPassword ? "text" : "password"} value={confirmPassword} onChange={e => onFieldChange('confirmPassword', e.target.value)} className={`w-full bg-slate-900/50 border ${password && confirmPassword && password !== confirmPassword ? 'border-rose-500/50 focus:border-rose-500 focus:ring-rose-500' : 'border-slate-700 focus:border-indigo-500 focus:ring-indigo-500'} rounded-xl pl-11 pr-4 py-3 text-slate-100 transition-all`} placeholder="••••••••" />
          </div>
        </div>
      </div>
    </div>
  );
}
