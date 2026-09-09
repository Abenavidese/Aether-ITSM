import { Building2, ChevronDown } from 'lucide-react';

interface StepOrganizationProps {
  companyName: string;
  companySize: string;
  industry: string;
  onFieldChange: (field: string, value: string) => void;
}

export function StepOrganization({ companyName, companySize, industry, onFieldChange }: StepOrganizationProps) {
  return (
    <div className="space-y-5 animate-in fade-in slide-in-from-right-4 duration-500">
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Company Name</label>
        <div className="relative group">
          <Building2 className="absolute left-4 top-3.5 text-slate-500 group-focus-within:text-indigo-400 transition-colors" size={18} />
          <input type="text" value={companyName} onChange={e => onFieldChange('companyName', e.target.value)} className="w-full bg-slate-900/50 border border-slate-700 rounded-xl pl-11 pr-4 py-3 text-slate-100 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all" placeholder="Acme Corp" />
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Company Size</label>
        <div className="relative group">
          <select value={companySize} onChange={e => onFieldChange('companySize', e.target.value)} className="w-full bg-slate-900/50 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all appearance-none cursor-pointer hover:bg-slate-800/50">
            <option value="" disabled>Select employee count</option>
            <option value="1-50">1 - 50 employees</option>
            <option value="51-200">51 - 200 employees</option>
            <option value="201-1000">201 - 1,000 employees</option>
            <option value="1000+">1,000+ employees</option>
          </select>
          <ChevronDown className="absolute right-4 top-3.5 text-slate-500 pointer-events-none" size={16} />
        </div>
      </div>
      
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Industry</label>
        <div className="relative group">
          <select value={industry} onChange={e => onFieldChange('industry', e.target.value)} className="w-full bg-slate-900/50 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all appearance-none cursor-pointer hover:bg-slate-800/50">
            <option value="" disabled>Select your sector</option>
            <option value="technology">Technology & Software</option>
            <option value="finance">Finance & Banking</option>
            <option value="healthcare">Healthcare</option>
            <option value="education">Education</option>
            <option value="retail">Retail & E-commerce</option>
            <option value="other">Other</option>
          </select>
          <ChevronDown className="absolute right-4 top-3.5 text-slate-500 pointer-events-none" size={16} />
        </div>
      </div>
    </div>
  );
}
