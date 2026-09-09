import { Check, X } from 'lucide-react';
import type { Ticket } from '../hooks/useSimulation';

interface HumanGatePanelProps {
  tickets: Ticket[];
  onApprove: (id: string, approved: boolean) => void;
}

export function HumanGatePanel({ tickets, onApprove }: HumanGatePanelProps) {
  const pausedTickets = tickets.filter(t => t.status === 'paused');

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-2">Human Gate (L3)</h2>
      
      {pausedTickets.length === 0 && (
        <div className="border border-dashed border-slate-700 rounded-xl p-8 text-center text-slate-500 text-sm">
          No tickets pending human approval.
        </div>
      )}

      {pausedTickets.map(t => (
        <div key={t.id} className="bg-slate-800/80 border border-amber-500/30 rounded-xl p-4 shadow-[0_0_15px_rgba(245,158,11,0.1)]">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-mono text-amber-400">{t.id}</span>
            <span className="text-xs bg-amber-500/20 text-amber-300 px-2 py-1 rounded">Risk 3</span>
          </div>
          <p className="text-sm mb-4">{t.summary}</p>
          
          <div className="bg-slate-900 rounded p-3 mb-4 text-xs font-mono text-slate-400">
            <span className="text-indigo-400">Proposed Plan:</span><br/>
            1. Connect to AWS IAM<br/>
            2. Add user to group 'admin'<br/>
            3. Notify user via email
          </div>

          <div className="flex gap-2">
            <button 
              onClick={() => onApprove(t.id, true)}
              className="flex-1 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/30 py-2 rounded-lg flex items-center justify-center gap-1 text-sm font-medium transition-colors"
            >
              <Check size={16} /> Approve
            </button>
            <button 
              onClick={() => onApprove(t.id, false)}
              className="flex-1 bg-rose-600/20 hover:bg-rose-600/30 text-rose-400 border border-rose-500/30 py-2 rounded-lg flex items-center justify-center gap-1 text-sm font-medium transition-colors"
            >
              <X size={16} /> Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
