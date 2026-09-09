import { PlayCircle } from 'lucide-react';
import { MetricsBar } from '../components/MetricsBar';
import { TicketCard } from '../components/TicketCard';
import { GraphVisualizer } from '../components/GraphVisualizer';
import { HumanGatePanel } from '../components/HumanGatePanel';
import { useSimulation } from '../hooks/useSimulation';

export function AdminDashboardPage() {
  const { activeNode, processingTicketId, tickets, runSimulation, approveTicket } = useSimulation();

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

        <div className="col-span-3">
          <HumanGatePanel tickets={tickets} onApprove={approveTicket} />
        </div>
      </div>
    </div>
  );
}
