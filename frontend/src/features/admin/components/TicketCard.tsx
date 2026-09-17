import type { ReactElement } from "react";
import { AlertTriangle, CheckCircle2, Clock, GitPullRequestArrow } from "lucide-react";
import type { DashboardTicket } from "../types";

interface TicketCardProps {
  ticket: DashboardTicket;
  isActive?: boolean;
}

const STATUS_STYLE: Record<DashboardTicket["status"], string> = {
  resolved: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
  open: "text-blue-400 bg-blue-400/10 border-blue-400/20",
  pending_human: "text-amber-400 bg-amber-400/10 border-amber-400/20",
  escalated: "text-rose-400 bg-rose-400/10 border-rose-400/20",
};

const STATUS_ICON: Record<DashboardTicket["status"], ReactElement> = {
  resolved: <CheckCircle2 size={16} />,
  open: <Clock size={16} />,
  pending_human: <AlertTriangle size={16} />,
  escalated: <GitPullRequestArrow size={16} />,
};

export function TicketCard({ ticket, isActive = false }: TicketCardProps) {
  const statusClass = STATUS_STYLE[ticket.status] ?? STATUS_STYLE.open;
  const statusIcon = STATUS_ICON[ticket.status] ?? STATUS_ICON.open;

  return (
    <div className={`p-4 rounded-xl border transition-all duration-300 ${
      isActive
        ? "bg-slate-700/80 border-indigo-500/50 shadow-[0_0_15px_rgba(99,102,241,0.2)]"
        : "bg-slate-800/40 border-slate-700/50 hover:bg-slate-700/50"
    }`}>
      <div className="flex justify-between items-start mb-2">
        <span className="text-xs font-mono text-slate-400 bg-slate-900/50 px-2 py-1 rounded">
          {ticket.external_id || ticket.id.slice(0, 8)}
        </span>
        <div className={`flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-full border ${statusClass}`}>
          {statusIcon}
          <span>{ticket.urgency}</span>
        </div>
      </div>

      <h3 className="text-slate-200 font-medium text-sm leading-tight mb-2">
        {ticket.title}
      </h3>

      <div className="flex justify-between items-center text-xs">
        <span className="text-slate-500 capitalize">{ticket.category}</span>
        <span className="text-slate-400 uppercase tracking-wider text-[10px] font-bold">
          {ticket.status.replace('_', ' ')}
        </span>
      </div>

      {ticket.github_issue_url && (
        <a
          href={ticket.github_issue_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-block text-xs text-indigo-400 hover:text-indigo-300 underline"
        >
          View GitHub issue
        </a>
      )}
    </div>
  );
}
