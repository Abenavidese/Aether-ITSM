import { BarChart3, HelpCircle } from 'lucide-react';
import type { KnowledgeInsights } from '../types';

/** What the knowledge base answered — and what it couldn't (Fase 14.7). */
export function KnowledgeInsightsCard({ insights }: { insights: KnowledgeInsights }) {
  const emptyPct = insights.empty_rate === null ? '—' : `${Math.round(insights.empty_rate * 100)}%`;
  return (
    <div className="mt-8 grid gap-4 md:grid-cols-2">
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center gap-2 text-slate-300 font-medium mb-4">
          <BarChart3 size={16} /> Last {insights.days} days
        </div>
        <dl className="grid grid-cols-3 gap-3 text-center">
          <div><dt className="text-xs text-slate-500">Searches</dt><dd className="text-lg text-white">{insights.searches}</dd></div>
          <div><dt className="text-xs text-slate-500">No answer</dt><dd className="text-lg text-white">{emptyPct}</dd></div>
          <div><dt className="text-xs text-slate-500">p50</dt><dd className="text-lg text-white">{insights.latency_p50_ms ?? '—'} ms</dd></div>
        </dl>
        {insights.top_documents.length > 0 && (
          <div className="mt-4 text-sm">
            <p className="text-xs text-slate-500 mb-1">Most used</p>
            {insights.top_documents.map(d => (
              <p key={d.id} className="text-slate-300 truncate">{d.filename} <span className="text-slate-500">· {d.uses}</span></p>
            ))}
          </div>
        )}
        {insights.unused_documents.length > 0 && (
          <p className="mt-3 text-xs text-slate-500">
            Never used: {insights.unused_documents.map(d => d.filename).join(', ')}
          </p>
        )}
      </div>
      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-5">
        <div className="flex items-center gap-2 text-slate-300 font-medium mb-1">
          <HelpCircle size={16} /> Questions without an answer
        </div>
        <p className="text-xs text-slate-500 mb-3">What your documentation doesn't cover yet.</p>
        {insights.unanswered_questions.length === 0 ? (
          <p className="text-sm text-slate-500">None — every search found relevant documentation.</p>
        ) : (
          <ul className="space-y-1.5 text-sm max-h-48 overflow-y-auto">
            {insights.unanswered_questions.map((q, i) => (
              <li key={i} className="text-slate-300 truncate" title={q.query}>“{q.query}”</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
