import { Send } from 'lucide-react';

interface ChatInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (e: React.FormEvent) => void;
}

export function ChatInput({ value, onChange, onSubmit }: ChatInputProps) {
  return (
    <div className="p-6 bg-slate-800/30 border-t border-slate-800">
      <form onSubmit={onSubmit} className="relative flex items-center">
        <input 
          type="text" 
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder="Type your issue in plain English (e.g. 'My VPN dropped')"
          className="w-full bg-slate-900 border border-slate-700 rounded-xl pl-4 pr-12 py-4 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all shadow-inner"
        />
        <button 
          type="submit" 
          disabled={!value.trim()}
          className="absolute right-2 p-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:hover:bg-indigo-600 text-white rounded-lg transition-colors"
        >
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
