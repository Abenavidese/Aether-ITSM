import { useState } from 'react';
import { BookOpen, Check, Info, RefreshCw, ShieldAlert, Trash2, Upload, X } from 'lucide-react';
import { useKnowledgeBase } from '../hooks/useKnowledgeBase';
import type { KnowledgeDocument, KnowledgeStatus } from '../types';
import { KnowledgeInsightsCard } from './KnowledgeInsightsCard';

const ALLOWED = ['.pdf', '.txt', '.md'];

const STATUS_STYLE: Record<KnowledgeStatus, { label: string; className: string }> = {
  queued: { label: 'Queued', className: 'bg-slate-500/10 text-slate-300 border-slate-500/20' },
  indexing: { label: 'Indexing…', className: 'bg-indigo-500/10 text-indigo-300 border-indigo-500/20 animate-pulse' },
  ready: { label: 'Indexed', className: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
  failed: { label: 'Failed', className: 'bg-rose-500/10 text-rose-400 border-rose-500/20' },
  pending_review: { label: 'Needs review', className: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
  rejected: { label: 'Rejected', className: 'bg-slate-500/10 text-slate-500 border-slate-500/20' },
};

const SOURCE_LABEL: Record<KnowledgeDocument['source_type'], string> = {
  company_policy: 'Company Policy',
  technical_repo: 'Technical Docs',
  ai_feedback: 'AI Correction',
};

function StatusCell({ doc }: { doc: KnowledgeDocument }) {
  const style = STATUS_STYLE[doc.status];
  // A new version indexing (or failed) while an older one keeps answering.
  const serving = doc.active_version && doc.active_version !== doc.version && doc.status !== 'ready'
    ? `Serving v${doc.active_version} meanwhile` : null;
  return (
    <div className="flex flex-col gap-1">
      <span className={`w-fit px-2.5 py-1 rounded-full text-xs font-medium border ${style.className}`}>
        {style.label}{doc.version > 1 ? ` · v${doc.version}` : ''}
      </span>
      {serving && <span className="text-xs text-slate-500">{serving}</span>}
      {doc.stale && <span className="text-xs text-amber-400">Indexed with an older model — re-index</span>}
      {doc.error && <span className="text-xs text-rose-400" title={doc.error}>{doc.error.slice(0, 80)}</span>}
      {doc.warnings.map((w, i) => <span key={i} className="text-xs text-amber-400/90">{w}</span>)}
    </div>
  );
}

export function KnowledgeBasePanel() {
  const kb = useKnowledgeBase();
  const [sourceType, setSourceType] = useState('company_policy');

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!ALLOWED.some(ext => file.name.toLowerCase().endsWith(ext))) {
      kb.setError('Only PDF, TXT and MD files are supported.');
      return;
    }
    await kb.upload(file, sourceType);
  };

  const handleDelete = (filename: string) => {
    if (confirm(`Remove ${filename} from the knowledge base?`)) kb.remove(filename);
  };

  if (kb.loading) return <div className="p-8 text-center text-slate-500 animate-pulse">Loading Knowledge Base...</div>;

  const pending = kb.documents.filter(d => d.status === 'pending_review');
  const listed = kb.documents.filter(d => d.status !== 'pending_review');
  const staleCount = kb.documents.filter(d => d.stale).length;

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-8 shadow-xl">
      <div className="flex items-center justify-between mb-8 pb-6 border-b border-slate-800">
        <div className="flex items-center gap-4">
          <div className="bg-emerald-500/20 p-4 rounded-xl text-emerald-400">
            <BookOpen size={24} />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white">Knowledge Base (RAG)</h2>
            <p className="text-sm text-slate-400">Policies and technical docs the assistant answers from — and cites.</p>
          </div>
        </div>
        <div className="flex gap-3">
          {staleCount > 0 && (
            <button onClick={() => kb.reindex()} className="border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 px-3 py-2 rounded-lg text-sm flex items-center gap-2">
              <RefreshCw size={14} /> Re-index {staleCount}
            </button>
          )}
          <select
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-300"
          >
            <option value="company_policy">Company Policy (General)</option>
            <option value="technical_repo">Technical Docs (Repo)</option>
          </select>
          <label className={`bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-2 cursor-pointer ${kb.uploading ? 'opacity-50 pointer-events-none' : ''}`}>
            <Upload size={16} /> {kb.uploading ? 'Uploading...' : 'Upload File'}
            <input type="file" accept={ALLOWED.join(',')} className="hidden" onChange={handleFileUpload} disabled={kb.uploading} />
          </label>
        </div>
      </div>

      {kb.notice && (
        <div className="mb-6 p-4 bg-indigo-500/10 border border-indigo-500/20 rounded-xl flex items-center gap-3 text-indigo-300 text-sm">
          <Info size={18} /> {kb.notice}
        </div>
      )}
      {kb.error && (
        <div className="mb-6 p-4 bg-rose-500/10 border border-rose-500/20 rounded-xl flex items-center gap-3 text-rose-400 text-sm">
          <ShieldAlert size={18} /> {kb.error}
        </div>
      )}

      {pending.length > 0 && (
        <div className="mb-8 p-5 bg-amber-500/5 border border-amber-500/20 rounded-xl">
          <p className="text-sm font-medium text-amber-300 mb-1">Corrections waiting for review</p>
          <p className="text-xs text-slate-400 mb-4">The assistant only learns from a correction after an admin approves it.</p>
          {pending.map(doc => (
            <div key={doc.id} className="flex items-start justify-between gap-4 py-3 border-t border-amber-500/10">
              <p className="text-sm text-slate-300 whitespace-pre-line">{doc.content}</p>
              <div className="flex gap-2 shrink-0">
                <button onClick={() => kb.review(doc.id, true)} className="p-2 rounded-lg text-emerald-400 hover:bg-emerald-500/10" title="Approve">
                  <Check size={16} />
                </button>
                <button onClick={() => kb.review(doc.id, false)} className="p-2 rounded-lg text-rose-400 hover:bg-rose-500/10" title="Reject">
                  <X size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {listed.length === 0 ? (
        <div className="text-center py-12 text-slate-500 bg-slate-900/30 rounded-xl border border-slate-800/50">
          <BookOpen size={32} className="mx-auto mb-3 opacity-20" />
          <p>No documents uploaded yet.</p>
          <p className="text-xs mt-1">Upload a PDF, TXT or MD file to teach the AI about your company.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 text-sm font-medium text-slate-500">
                <th className="pb-3 px-4 font-medium">Document</th>
                <th className="pb-3 px-4 font-medium">Type</th>
                <th className="pb-3 px-4 font-medium">Status</th>
                <th className="pb-3 px-4 font-medium">Chunks</th>
                <th className="pb-3 px-4 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {listed.map(doc => (
                <tr key={doc.id} className="border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors align-top">
                  <td className="py-4 px-4">
                    <span className="text-slate-200 font-medium">{doc.filename}</span>
                    {doc.pages ? <span className="block text-xs text-slate-500">{doc.pages} pages</span> : null}
                  </td>
                  <td className="py-4 px-4 text-slate-400">{SOURCE_LABEL[doc.source_type]}</td>
                  <td className="py-4 px-4"><StatusCell doc={doc} /></td>
                  <td className="py-4 px-4 text-slate-400">{doc.chunks || '—'}</td>
                  <td className="py-4 px-4 text-right">
                    <button
                      onClick={() => handleDelete(doc.filename)}
                      className="text-slate-500 hover:text-rose-400 p-2 rounded-lg hover:bg-rose-500/10 transition-colors"
                      title="Remove from Knowledge Base"
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {kb.insights && <KnowledgeInsightsCard insights={kb.insights} />}
    </div>
  );
}
