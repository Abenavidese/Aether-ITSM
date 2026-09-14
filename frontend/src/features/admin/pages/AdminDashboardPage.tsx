import { useEffect, useState } from 'react';
import { MetricsBar } from '../components/MetricsBar';
import { TicketCard } from '../components/TicketCard';
import { HumanGatePanel } from '../components/HumanGatePanel';
import { config } from '../../../config';

export function AdminDashboardPage() {
  
  const [dashboardData, setDashboardData] = useState<{
    metrics: { auto_deflection_rate: number, time_saved_hours: number, pending_human: number, cost_saved_usd: number },
    tickets: any[]
  } | null>(null);

  const fetchDashboard = async () => {
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/dashboard`, {
        credentials: 'include'
      });
      if (res.ok) {
        setDashboardData(await res.json());
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchDashboard();
    // Auto refresh every 30 seconds
    const interval = setInterval(fetchDashboard, 30000);
    return () => clearInterval(interval);
  }, []);

  const approveTicket = (ticketId: string, approved: boolean) => {
    console.log(`Ticket ${ticketId} human review: ${approved}`);
    // In Phase 2, this will send a real POST request to resolve/escalate the ticket
  };

  return (
    <div className="max-w-7xl mx-auto">
      <header className="flex justify-between items-end mb-8 border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-3xl font-bold bg-gradient-to-r from-indigo-400 to-cyan-400 bg-clip-text text-transparent mb-1">
            IT Command Center
          </h1>
          <p className="text-slate-400 text-sm mt-1">Aether ITSM Admin Dashboard (Live Sync)</p>
        </div>
      </header>

      <MetricsBar 
        autoDeflectionRate={dashboardData?.metrics?.auto_deflection_rate || 0}
        timeSavedHours={dashboardData?.metrics?.time_saved_hours || 0}
        pendingHuman={dashboardData?.metrics?.pending_human || 0}
      />

      <div className="grid grid-cols-12 gap-8">
        
        <div className="col-span-8 flex flex-col gap-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-2">Live Ticket Stream</h2>
          {dashboardData?.tickets?.length === 0 ? (
            <div className="p-8 text-center text-slate-500 bg-slate-900/50 rounded-xl border border-slate-800">
              No tickets found. The AI is waiting for new employee requests.
            </div>
          ) : (
            dashboardData?.tickets?.map(t => (
              <TicketCard key={t.id} ticket={t} isActive={false} />
            ))
          )}
        </div>

        <div className="col-span-4">
          <HumanGatePanel tickets={dashboardData?.tickets?.filter(t => t.status === 'pending_human') || []} onApprove={approveTicket} />
        </div>
      </div>
    </div>
  );
}
