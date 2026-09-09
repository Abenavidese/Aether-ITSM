import { ShieldAlert, Zap, Clock } from "lucide-react";

export function MetricsBar() {
  return (
    <div className="flex w-full gap-4 mb-6">
      <div className="flex-1 bg-slate-800/50 backdrop-blur-md border border-slate-700/50 rounded-xl p-4 flex items-center gap-4 shadow-lg">
        <div className="bg-indigo-500/20 p-3 rounded-lg text-indigo-400">
          <Zap size={24} />
        </div>
        <div>
          <p className="text-slate-400 text-sm font-medium">Auto-Deflection Rate</p>
          <p className="text-2xl font-bold text-slate-100">82.4%</p>
        </div>
      </div>

      <div className="flex-1 bg-slate-800/50 backdrop-blur-md border border-slate-700/50 rounded-xl p-4 flex items-center gap-4 shadow-lg">
        <div className="bg-emerald-500/20 p-3 rounded-lg text-emerald-400">
          <Clock size={24} />
        </div>
        <div>
          <p className="text-slate-400 text-sm font-medium">Est. Human Time Saved</p>
          <p className="text-2xl font-bold text-slate-100">142 hrs</p>
        </div>
      </div>

      <div className="flex-1 bg-slate-800/50 backdrop-blur-md border border-slate-700/50 rounded-xl p-4 flex items-center gap-4 shadow-lg">
        <div className="bg-rose-500/20 p-3 rounded-lg text-rose-400">
          <ShieldAlert size={24} />
        </div>
        <div>
          <p className="text-slate-400 text-sm font-medium">Pending Human Reviews</p>
          <p className="text-2xl font-bold text-slate-100">1</p>
        </div>
      </div>
    </div>
  );
}
