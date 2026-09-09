import { Briefcase, ChevronDown } from 'lucide-react';

interface StepPersonalizeProps {
  jobTitle: string;
  currentTool: string;
  primaryGoal: string;
  onFieldChange: (field: string, value: string) => void;
}

export function StepPersonalize({ jobTitle, currentTool, primaryGoal, onFieldChange }: StepPersonalizeProps) {
  return (
    <div className="space-y-5 animate-in fade-in slide-in-from-right-4 duration-500">
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Your Role</label>
        <div className="relative group">
          <Briefcase className="absolute left-4 top-3.5 text-slate-500 group-focus-within:text-indigo-400 transition-colors" size={18} />
          <input type="text" value={jobTitle} onChange={e => onFieldChange('jobTitle', e.target.value)} className="w-full bg-slate-900/50 border border-slate-700 rounded-xl pl-11 pr-4 py-3 text-slate-100 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all" placeholder="e.g. CTO, IT Admin, Developer" />
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Current ITSM Tool</label>
        <div className="relative group">
          <select value={currentTool} onChange={e => onFieldChange('currentTool', e.target.value)} className="w-full bg-slate-900/50 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all appearance-none cursor-pointer hover:bg-slate-800/50">
            <option value="" disabled>What are you using today?</option>
            <option value="jira">Jira Service Management</option>
            <option value="servicenow">ServiceNow</option>
            <option value="zendesk">Zendesk</option>
            <option value="freshservice">Freshservice</option>
            <option value="none">None / Spreadsheets</option>
            <option value="other">Other</option>
          </select>
          <ChevronDown className="absolute right-4 top-3.5 text-slate-500 pointer-events-none" size={16} />
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Primary Goal</label>
        <div className="relative group">
          <select value={primaryGoal} onChange={e => onFieldChange('primaryGoal', e.target.value)} className="w-full bg-slate-900/50 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all appearance-none cursor-pointer hover:bg-slate-800/50">
            <option value="" disabled>What brings you to Aether?</option>
            <option value="automate_l1">Automate L1 Support with AI</option>
            <option value="organize_tickets">Organize & Track IT Tickets</option>
            <option value="migration">Migrate from legacy ITSM</option>
            <option value="testing">Internal Testing / Evaluation</option>
          </select>
          <ChevronDown className="absolute right-4 top-3.5 text-slate-500 pointer-events-none" size={16} />
        </div>
      </div>
    </div>
  );
}
