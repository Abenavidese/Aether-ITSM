import { useEffect, useState } from 'react';
import { Activity } from 'lucide-react';
import { config } from '../../../config';

// Shape of GET /tenant/observability/usage (src/observability/usage.py).
type Usage = {
  period_days: number;
  totals: { llm_calls: number; input_tokens: number; output_tokens: number; cost_usd: number; priced: boolean };
  by_model: { model: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number }[];
  nodes: { node: string; count: number; p50_ms: number; p95_ms: number; error_rate: number }[];
};

const fmt = new Intl.NumberFormat();
const seconds = (ms: number) => `${(ms / 1000).toFixed(1)}s`;

// Real LLM usage from recorded agent traces (roadmap 2.4) — not the fixed
// "time saved" heuristic of the metrics bar.
export function UsagePanel() {
  const [usage, setUsage] = useState<Usage | null>(null);

  useEffect(() => {
    fetch(`${config.API_BASE_URL}/tenant/observability/usage?days=30`, { credentials: 'include' })
      .then(res => (res.ok ? res.json() : null))
      .then(setUsage)
      .catch(() => setUsage(null));
  }, []);

  if (!usage) return null;
  const { totals } = usage;

  return (
    <section className="bg-slate-900/50 border border-slate-800 rounded-xl p-4 mb-8">
      <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
        <Activity size={16} /> LLM usage · last {usage.period_days} days
      </h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4 text-sm">
        <div><div className="text-slate-500">Model calls</div><div className="text-xl font-semibold">{fmt.format(totals.llm_calls)}</div></div>
        <div><div className="text-slate-500">Input tokens</div><div className="text-xl font-semibold">{fmt.format(totals.input_tokens)}</div></div>
        <div><div className="text-slate-500">Output tokens</div><div className="text-xl font-semibold">{fmt.format(totals.output_tokens)}</div></div>
        <div>
          <div className="text-slate-500">Cost</div>
          <div className="text-xl font-semibold">${totals.cost_usd.toFixed(4)}</div>
          {!totals.priced && <div className="text-xs text-slate-500">no prices configured (local models)</div>}
        </div>
      </div>
      <div className="grid md:grid-cols-2 gap-6 text-xs">
        <table className="w-full">
          <thead className="text-slate-500 text-left"><tr><th>Model</th><th>Calls</th><th>Tokens in/out</th></tr></thead>
          <tbody>
            {usage.by_model.map(m => (
              <tr key={m.model} className="border-t border-slate-800">
                <td className="py-1 font-mono">{m.model}</td><td>{m.calls}</td>
                <td>{fmt.format(m.input_tokens)} / {fmt.format(m.output_tokens)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <table className="w-full">
          <thead className="text-slate-500 text-left"><tr><th>Node</th><th>Runs</th><th>p50</th><th>p95</th><th>Errors</th></tr></thead>
          <tbody>
            {usage.nodes.map(n => (
              <tr key={n.node} className="border-t border-slate-800">
                <td className="py-1 font-mono">{n.node}</td><td>{n.count}</td>
                <td>{seconds(n.p50_ms)}</td><td>{seconds(n.p95_ms)}</td><td>{(n.error_rate * 100).toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
