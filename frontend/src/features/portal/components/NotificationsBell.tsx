import { useState } from 'react';
import { Bell, CheckCheck, CheckCircle2, Clock, ExternalLink, GitPullRequestArrow, Wrench } from 'lucide-react';
import type { ReactElement } from 'react';
import type { AppNotification } from '../hooks/useNotifications';

const ICON: Record<AppNotification['kind'], ReactElement> = {
  ticket_opened: <Clock size={16} className="text-blue-400" />,
  pending_human: <Clock size={16} className="text-amber-400" />,
  escalated: <Wrench size={16} className="text-rose-400" />,
  issue_opened: <GitPullRequestArrow size={16} className="text-slate-400" />,
  fix_proposed: <GitPullRequestArrow size={16} className="text-indigo-400" />,
  resolved: <CheckCircle2 size={16} className="text-emerald-400" />,
};

interface Props {
  items: AppNotification[];
  unread: number;
  onMarkAllRead: () => void;
}

export function NotificationsBell({ items, unread, onMarkAllRead }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative ml-auto">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="relative p-2 rounded-lg text-slate-300 hover:bg-slate-700/50"
        aria-label={`Notificaciones (${unread} sin leer)`}
      >
        <Bell size={20} />
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-rose-500 text-[10px] font-bold text-white flex items-center justify-center">
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-96 max-h-[60vh] overflow-y-auto z-20 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
            <span className="text-sm font-semibold text-slate-200">Notificaciones</span>
            {unread > 0 && (
              <button type="button" onClick={onMarkAllRead}
                      className="flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300">
                <CheckCheck size={14} /> Marcar todo como leído
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <p className="p-6 text-sm text-center text-slate-500">Aún no tienes notificaciones.</p>
          ) : (
            <ul className="divide-y divide-slate-800">
              {items.map(n => (
                <li key={n.id} className={`px-4 py-3 flex gap-3 ${n.read ? 'opacity-70' : 'bg-slate-800/40'}`}>
                  <div className="mt-0.5">{ICON[n.kind] ?? <Bell size={16} />}</div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-100">{n.title}</p>
                    <p className="text-xs text-slate-400 mt-0.5">{n.body}</p>
                    <div className="flex items-center gap-3 mt-1 text-[11px] text-slate-500">
                      {n.created_at && <span>{new Date(n.created_at).toLocaleString()}</span>}
                      {n.link && (
                        <a href={n.link} target="_blank" rel="noreferrer"
                           className="flex items-center gap-1 text-indigo-400 hover:text-indigo-300">
                          Ver en GitHub <ExternalLink size={11} />
                        </a>
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
