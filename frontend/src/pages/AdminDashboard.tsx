import { useState } from 'react';
import { MetricsBar } from '../components/admin/MetricsBar';
import { TicketCard, type Ticket } from '../components/admin/TicketCard';
import { GraphVisualizer } from '../components/admin/GraphVisualizer';
import { PlayCircle, Check, X } from 'lucide-react';

export function AdminDashboard() {
  const [activeNode, setActiveNode] = useState<string>("idle");
  const [processingTicketId, setProcessingTicketId] = useState<string | null>(null);
  
  const [tickets, setTickets] = useState<Ticket[]>([
    { id: 'IT-101', summary: 'VPN connection dropping', user_id: 'alice.m', risk_level: 1, status: 'pending' },
    { id: 'IT-102', summary: 'Need Docker installed', user_id: 'bob.d', risk_level: 2, status: 'pending' },
    { id: 'IT-103', summary: 'Grant AWS Admin for Project X', user_id: 'charlie.c', risk_level: 3, status: 'pending' },
    { id: 'IT-104', summary: 'OOM Errors in Prod DB', user_id: 'diana.p', risk_level: 4, status: 'pending' },
  ]);

  const runSimulation = async () => {
    for (let i = 0; i < tickets.length; i++) {
      const t = tickets[i];
      setProcessingTicketId(t.id);
      
      setTickets(prev => prev.map(pt => pt.id === t.id ? { ...pt, status: 'processing' } : pt));
      
      setActiveNode("classify");
      await new Promise(r => setTimeout(r, 1500));
      
      setActiveNode("route");
      await new Promise(r => setTimeout(r, 1000));
      
      if (t.risk_level <= 2) {
        setActiveNode("execute");
        await new Promise(r => setTimeout(r, 2000));
        setTickets(prev => prev.map(pt => pt.id === t.id ? { ...pt, status: 'resolved' } : pt));
      } else if (t.risk_level === 3) {
        setActiveNode("draft");
        setTickets(prev => prev.map(pt => pt.id === t.id ? { ...pt, status: 'paused' } : pt));
        setProcessingTicketId(null);
        break; 
      } else {
        setActiveNode("escalate");
        await new Promise(r => setTimeout(r, 1500));
        setTickets(prev => prev.map(pt => pt.id === t.id ? { ...pt, status: 'escalated' } : pt));
      }
      
      setActiveNode("idle");
      setProcessingTicketId(null);
    }
  };

  const approveTicket = async (id: string, approved: boolean) => {
    setActiveNode("execute");
    await new Promise(r => setTimeout(r, 1500));
    setTickets(prev => prev.map(pt => pt.id === id ? { ...pt, status: approved ? 'resolved' : 'escalated' } : pt));
    setActiveNode("idle");
  };

  return (
    <div className="max-w-7xl mx-auto">
      <header className="flex justify-between items-end mb-8 border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-3xl font-bold bg-gradient-to-r from-indigo-400 to-cyan-400 bg-clip-text text-transparent">
            IT Command Center
          </h1>
          <p className="text-slate-400 text-sm mt-1">Aether ITSM Admin Dashboard</p>
        </div>
        
        <button 
          onClick={runSimulation}
          className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg font-medium transition-colors"
        >
          <PlayCircle size={20} />
          Simulate Batch
        </button>
      </header>

      <MetricsBar />

      <div className="grid grid-cols-12 gap-8">
        
        <div className="col-span-3 flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-2">Ticket Stream</h2>
          {tickets.map(t => (
            <TicketCard key={t.id} ticket={t} isActive={t.id === processingTicketId} />
          ))}
        </div>

        <div className="col-span-6">
           <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-2 text-center">Agent Orchestration</h2>
           <GraphVisualizer activeNode={activeNode} />
        </div>

        <div className="col-span-3 flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-2">Human Gate (L3)</h2>
          
          {tickets.filter(t => t.status === 'paused').length === 0 && (
            <div className="border border-dashed border-slate-700 rounded-xl p-8 text-center text-slate-500 text-sm">
              No tickets pending human approval.
            </div>
          )}

          {tickets.filter(t => t.status === 'paused').map(t => (
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
                  onClick={() => approveTicket(t.id, true)}
                  className="flex-1 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/30 py-2 rounded-lg flex items-center justify-center gap-1 text-sm font-medium transition-colors"
                >
                  <Check size={16} /> Approve
                </button>
                <button 
                  onClick={() => approveTicket(t.id, false)}
                  className="flex-1 bg-rose-600/20 hover:bg-rose-600/30 text-rose-400 border border-rose-500/30 py-2 rounded-lg flex items-center justify-center gap-1 text-sm font-medium transition-colors"
                >
                  <X size={16} /> Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
