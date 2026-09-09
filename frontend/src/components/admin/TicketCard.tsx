import { AlertTriangle, CheckCircle2, Shield, Search } from "lucide-react";

export type Ticket = {
  id: string;
  summary: string;
  user_id: string;
  risk_level: number;
  status: "pending" | "processing" | "paused" | "resolved" | "escalated";
};

interface TicketCardProps {
  ticket: Ticket;
  isActive?: boolean;
}

export function TicketCard({ ticket, isActive = false }: TicketCardProps) {
  
  const getRiskColor = (risk: number) => {
    if (risk === 0) return "text-emerald-400 bg-emerald-400/10 border-emerald-400/20";
    if (risk <= 2) return "text-blue-400 bg-blue-400/10 border-blue-400/20";
    if (risk === 3) return "text-amber-400 bg-amber-400/10 border-amber-400/20";
    return "text-rose-400 bg-rose-400/10 border-rose-400/20";
  };

  const getRiskIcon = (risk: number) => {
    if (risk === 0) return <Search size={16} />;
    if (risk <= 2) return <CheckCircle2 size={16} />;
    if (risk === 3) return <Shield size={16} />;
    return <AlertTriangle size={16} />;
  };

  const riskClass = getRiskColor(ticket.risk_level);

  return (
    <div className={`p-4 rounded-xl border transition-all duration-300 ${
      isActive 
        ? "bg-slate-700/80 border-indigo-500/50 shadow-[0_0_15px_rgba(99,102,241,0.2)]" 
        : "bg-slate-800/40 border-slate-700/50 hover:bg-slate-700/50"
    }`}>
      <div className="flex justify-between items-start mb-2">
        <span className="text-xs font-mono text-slate-400 bg-slate-900/50 px-2 py-1 rounded">
          {ticket.id}
        </span>
        <div className={`flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full border ${riskClass}`}>
          {getRiskIcon(ticket.risk_level)}
          <span>Risk {ticket.risk_level}</span>
        </div>
      </div>
      
      <h3 className="text-slate-200 font-medium text-sm leading-tight mb-2">
        {ticket.summary}
      </h3>
      
      <div className="flex justify-between items-center text-xs">
        <span className="text-slate-500">{ticket.user_id}</span>
        <span className="text-slate-400 uppercase tracking-wider text-[10px] font-bold">
          {ticket.status}
        </span>
      </div>
    </div>
  );
}
