import { Brain, ArrowRight, Network, ShieldCheck, Database, Wrench } from "lucide-react";

interface NodeProps {
  label: string;
  icon: React.ReactNode;
  isActive: boolean;
  isPast: boolean;
}

function GraphNode({ label, icon, isActive, isPast }: NodeProps) {
  return (
    <div className={`flex flex-col items-center justify-center p-4 rounded-xl border-2 transition-all duration-500 w-32 h-24
      ${isActive 
        ? "bg-indigo-500/20 border-indigo-400 text-indigo-300 shadow-[0_0_20px_rgba(99,102,241,0.4)] scale-110" 
        : isPast 
          ? "bg-slate-800 border-emerald-500/50 text-emerald-400" 
          : "bg-slate-800/30 border-slate-700/50 text-slate-500"
      }`}
    >
      <div className={`mb-2 ${isActive ? "animate-pulse" : ""}`}>
        {icon}
      </div>
      <span className="text-xs font-semibold text-center leading-tight">{label}</span>
    </div>
  );
}

export function GraphVisualizer({ activeNode = "classify" }: { activeNode: string }) {
  const nodes = ["classify", "route", "execute", "draft", "escalate"];
  const activeIdx = nodes.indexOf(activeNode);

  return (
    <div className="bg-slate-900/50 border border-slate-700/50 rounded-2xl p-8 flex flex-col items-center relative overflow-hidden">
      
      {/* Decorative Background */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[80%] h-[200px] bg-indigo-500/10 blur-[100px] rounded-full pointer-events-none" />

      <div className="flex items-center gap-2 mb-8 text-indigo-400">
        <Network size={20} />
        <h2 className="font-semibold uppercase tracking-wider text-sm">LangGraph Agent Core</h2>
      </div>

      <div className="flex items-center justify-center relative z-10 w-full max-w-2xl">
        
        {/* Node 1 */}
        <GraphNode 
          label="Classify & Risk" 
          icon={<Brain size={24} />} 
          isActive={activeNode === "classify"} 
          isPast={activeIdx > 0} 
        />
        
        <ArrowRight className={`mx-2 ${activeIdx >= 1 ? "text-indigo-400" : "text-slate-700"}`} size={24} />

        {/* Node 2 */}
        <GraphNode 
          label="Router Edge" 
          icon={<Network size={24} />} 
          isActive={activeNode === "route"} 
          isPast={activeIdx > 1} 
        />
        
        <div className="flex flex-col mx-4 gap-6 relative">
          
          {/* Top Path */}
          <div className="flex items-center">
            <ArrowRight className={`mr-2 ${activeIdx >= 2 ? "text-indigo-400" : "text-slate-700"}`} size={24} />
            <GraphNode 
              label="Execute MCP" 
              icon={<Database size={24} />} 
              isActive={activeNode === "execute"} 
              isPast={activeNode === "execute" && activeIdx > 2} 
            />
          </div>

          {/* Middle Path */}
          <div className="flex items-center">
            <ArrowRight className={`mr-2 ${activeNode === "draft" ? "text-indigo-400" : "text-slate-700"}`} size={24} />
            <GraphNode 
              label="Draft Plan (Pause)" 
              icon={<Wrench size={24} />} 
              isActive={activeNode === "draft"} 
              isPast={false} 
            />
          </div>

          {/* Bottom Path */}
          <div className="flex items-center">
            <ArrowRight className={`mr-2 ${activeNode === "escalate" ? "text-indigo-400" : "text-slate-700"}`} size={24} />
            <GraphNode 
              label="Escalate" 
              icon={<ShieldCheck size={24} />} 
              isActive={activeNode === "escalate"} 
              isPast={false} 
            />
          </div>
        </div>
      </div>
    </div>
  );
}
