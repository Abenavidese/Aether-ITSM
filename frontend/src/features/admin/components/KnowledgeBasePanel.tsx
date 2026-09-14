import { useState, useEffect } from 'react';
import { BookOpen, Upload, Trash2, ShieldAlert } from 'lucide-react';
import { config } from '../../../config';

export function KnowledgeBasePanel() {
  const [files, setFiles] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [sourceType, setSourceType] = useState('company_policy');

  const fetchFiles = async () => {
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/knowledge`, {
        credentials: 'include'
      });
      if (res.ok) {
        setFiles(await res.json());
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFiles();
  }, []);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.endsWith('.pdf') && !file.name.endsWith('.txt')) {
      setError('Only PDF and TXT files are supported.');
      return;
    }

    setIsUploading(true);
    setError('');

    const formData = new FormData();
    formData.append('file', file);
    formData.append('source_type', sourceType);

    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/knowledge`, {
        method: 'POST',
        credentials: 'include',
        body: formData
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to upload document');
      }

      await fetchFiles();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsUploading(false);
      // Reset input
      e.target.value = '';
    }
  };

  const handleDelete = async (filename: string) => {
    if (!confirm(`Are you sure you want to delete ${filename}?`)) return;
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/knowledge/${filename}`, {
        method: 'DELETE',
        credentials: 'include'
      });
      if (res.ok) fetchFiles();
      else {
        const data = await res.json();
        alert(data.detail || 'Failed to delete file');
      }
    } catch (err) {
      console.error(err);
    }
  };

  if (loading) return <div className="p-8 text-center text-slate-500 animate-pulse">Loading Knowledge Base...</div>;

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-8 shadow-xl">
      <div className="flex items-center justify-between mb-8 pb-6 border-b border-slate-800">
        <div className="flex items-center gap-4">
          <div className="bg-emerald-500/20 p-4 rounded-xl text-emerald-400">
            <BookOpen size={24} />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white">Knowledge Base (RAG)</h2>
            <p className="text-sm text-slate-400">Upload guidelines and docs to train your company's AI Agent.</p>
          </div>
        </div>
        <div className="flex gap-4">
          <select 
            value={sourceType} 
            onChange={(e) => setSourceType(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-300"
          >
            <option value="company_policy">Company Policy (General)</option>
            <option value="technical_repo">Technical Docs (Repo)</option>
          </select>
          <label className="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-2 cursor-pointer disabled:opacity-50">
            <Upload size={16} /> {isUploading ? 'Uploading...' : 'Upload File'}
            <input 
              type="file" 
              accept=".pdf,.txt" 
              className="hidden" 
              onChange={handleFileUpload} 
              disabled={isUploading}
            />
          </label>
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-rose-500/10 border border-rose-500/20 rounded-xl flex items-center gap-3 text-rose-400 text-sm">
          <ShieldAlert size={18} />
          {error}
        </div>
      )}

      {files.length === 0 ? (
        <div className="text-center py-12 text-slate-500 bg-slate-900/30 rounded-xl border border-slate-800/50">
          <BookOpen size={32} className="mx-auto mb-3 opacity-20" />
          <p>No documents uploaded yet.</p>
          <p className="text-xs mt-1">Upload a PDF or TXT to teach the AI about your company.</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 text-sm font-medium text-slate-500">
                <th className="pb-3 px-4 font-medium">Document Name</th>
                <th className="pb-3 px-4 font-medium">Source Type</th>
                <th className="pb-3 px-4 font-medium">Status</th>
                <th className="pb-3 px-4 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {files.map((file: any) => (
                <tr key={file.filename} className="border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors">
                  <td className="py-4 px-4">
                    <span className="text-slate-200 font-medium">{file.filename}</span>
                  </td>
                  <td className="py-4 px-4 text-slate-400">
                    <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${file.source_type === 'company_policy' ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20' : 'bg-orange-500/10 text-orange-400 border border-orange-500/20'}`}>
                      {file.source_type === 'company_policy' ? 'Company Policy' : 'Technical Docs'}
                    </span>
                  </td>
                  <td className="py-4 px-4 text-slate-400">
                    <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      Indexed
                    </span>
                  </td>
                  <td className="py-4 px-4 text-right">
                    <button 
                      onClick={() => handleDelete(file.filename)}
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
    </div>
  );
}
