import { useState } from 'react';
import { Check, BrainCircuit } from 'lucide-react';
import type { DashboardTicket } from '../types';

interface HumanGatePanelProps {
  tickets: DashboardTicket[];
  onApprove: (externalId: string, approved: boolean, feedback?: string) => void;
}

export function HumanGatePanel({ tickets, onApprove }: HumanGatePanelProps) {
  // Backend status for a Risk-3 ticket paused on draft_plan is "pending_human"
  // (see src/agent/graph.py interrupt_after=["draft_plan"] and
  // _sync_ticket_from_snapshot in src/api/routes.py) — this used to filter on
  // "paused", a status the real API never sends, so the gate was always empty.
  const pausedTickets = tickets.filter(t => t.status === 'pending_human');
  const [feedback, setFeedback] = useState<Record<string, string>>({});

  const handleFeedbackChange = (id: string, value: string) => {
    setFeedback(prev => ({ ...prev, [id]: value }));
  };

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-2">Human Gate (L3)</h2>

      {pausedTickets.length === 0 && (
        <div className="border border-dashed border-slate-700 rounded-xl p-8 text-center text-slate-500 text-sm">
          No tickets pending human approval.
        </div>
      )}

      {pausedTickets.map(t => {
        const key = t.external_id || t.id;
        return (
          <div key={t.id} className="bg-slate-800/80 border border-amber-500/30 rounded-xl p-4 shadow-[0_0_15px_rgba(245,158,11,0.1)]">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono text-amber-400">{key}</span>
              <span className="text-xs bg-amber-500/20 text-amber-300 px-2 py-1 rounded">Awaiting approval</span>
            </div>
            <p className="text-sm mb-4">{t.title}</p>

            <div className="bg-slate-900 rounded p-3 mb-4 text-xs font-mono text-slate-400 whitespace-pre-wrap">
              <span className="text-indigo-400">Description:</span><br />
              {t.description}
            </div>

            {/* What the admin approves is exactly this plan + action (Fase 11.2):
                approving without seeing it was approving blind. Rendered as
                plain text — it contains LLM output. */}
            <div className="bg-slate-900 rounded p-3 mb-4 text-xs font-mono text-slate-300 whitespace-pre-wrap border border-amber-500/20">
              <span className="text-amber-400">Proposed plan:</span><br />
              {t.proposed_plan || 'No plan recorded for this ticket.'}
            </div>

            <div className="mb-4">
              <input
                type="text"
                placeholder="Why reject? (Teaches the AI for next time)"
                value={feedback[t.id] || ''}
                onChange={(e) => handleFeedbackChange(t.id, e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded p-2 text-xs text-slate-300 placeholder-slate-600 focus:border-amber-500/50 outline-none"
              />
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => onApprove(key, true)}
                className="flex-1 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/30 py-2 rounded-lg flex items-center justify-center gap-1 text-sm font-medium transition-colors"
              >
                <Check size={16} /> Approve
              </button>
              <button
                onClick={() => onApprove(key, false, feedback[t.id])}
                className="flex-1 bg-rose-600/20 hover:bg-rose-600/30 text-rose-400 border border-rose-500/30 py-2 rounded-lg flex items-center justify-center gap-1 text-sm font-medium transition-colors"
              >
                <BrainCircuit size={16} /> {feedback[t.id] ? 'Teach & Reject' : 'Reject'}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
