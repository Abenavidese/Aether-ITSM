import { useState, useEffect } from 'react';
import { KeyRound, Webhook, Link2, Copy, CheckCircle2, GitBranch, Loader2, Activity, Plus, Trash2, Eye, EyeOff } from 'lucide-react';
import { config } from '../../../config';

type MonitoredService = { name: string; url: string };

export function IntegrationPanel() {

  const [settings, setSettings] = useState<any>(null);
  const [copied, setCopied] = useState(false);
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState<{status: 'success' | 'error', message: string} | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [editForm, setEditForm] = useState({ github_token: '', github_user: '', github_repo_name: '' });
  const [services, setServices] = useState<MonitoredService[]>([]);
  const [isEditingServices, setIsEditingServices] = useState(false);

  const fetchSettings = async () => {
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/settings`, {
        credentials: 'include'
      });
      if (res.ok) {
        const data = await res.json();
        setSettings(data);
        
        let user = '';
        let repo = '';
        if (data.github_repo) {
          const parts = data.github_repo.split('/');
          user = parts[0] || '';
          repo = parts[1] || '';
        }
        
        setEditForm({
          // Never prefill from data.github_token — the backend deliberately
          // sends the literal string "MASKED" there, never the real
          // decrypted value (unlike api_key), so this field must always
          // start blank and only overwrite the stored token when the admin
          // actually types a new one (see handleSaveSettings).
          github_token: '',
          github_user: user,
          github_repo_name: repo
        });
        setServices(data.monitored_services || []);
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleCopy = () => {
    if (settings?.api_key) {
      navigator.clipboard.writeText(settings.api_key);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleSaveSettings = async () => {
    setTestResult(null);
    const body: Record<string, string> = {};
    // Blank means "leave the stored token as-is" — the field never gets
    // prefilled with the real value (see fetchSettings), so an empty string
    // here means the admin didn't intend to change it, not that they want
    // to wipe it out.
    if (editForm.github_token.trim()) {
      body.github_token = editForm.github_token;
    }
    // Only send github_repo when both halves are actually filled — sending
    // "/" (both empty) or "owner/" (one empty) always 422s server-side
    // (GITHUB_REPO_PATTERN in src/tenant/router.py), which used to silently
    // reject the WHOLE save, token included, with nothing shown to the user.
    if (editForm.github_user.trim() && editForm.github_repo_name.trim()) {
      body.github_repo = `${editForm.github_user}/${editForm.github_repo_name}`;
    }
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/settings`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (res.ok) {
        setIsEditing(false);
        fetchSettings(); // Refresh
      } else {
        const data = await res.json().catch(() => ({}));
        setTestResult({ status: 'error', message: data.detail || 'Failed to save settings.' });
      }
    } catch (err) {
      setTestResult({ status: 'error', message: 'Failed to reach backend' });
    }
  };

  const handleSaveServices = async () => {
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/settings`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          monitored_services: services.filter(s => s.name.trim() && s.url.trim())
        })
      });
      if (res.ok) {
        setIsEditingServices(false);
        fetchSettings();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const updateService = (index: number, field: keyof MonitoredService, value: string) => {
    setServices(prev => prev.map((s, i) => i === index ? { ...s, [field]: value } : s));
  };

  const addService = () => setServices(prev => [...prev, { name: '', url: '' }]);
  const removeService = (index: number) => setServices(prev => prev.filter((_, i) => i !== index));

  const handleTestConnection = async () => {
    setTestLoading(true);
    setTestResult(null);
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/test-github`, {
        credentials: 'include'
      });
      const data = await res.json();
      if (res.ok) {
        setTestResult({ status: 'success', message: `${data.message} (Issues: ${data.open_issues})` });
      } else {
        setTestResult({ status: 'error', message: data.detail || 'Connection failed' });
      }
    } catch (err) {
      setTestResult({ status: 'error', message: 'Failed to reach backend' });
    } finally {
      setTestLoading(false);
    }
  };

  if (!settings) return <div className="p-8 text-center text-slate-500 animate-pulse">Loading Integration Settings...</div>;

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-8 shadow-xl">
      <div className="flex items-center gap-4 mb-8 pb-6 border-b border-slate-800">
        <div className="bg-indigo-500/20 p-4 rounded-xl text-indigo-400">
          <Link2 size={24} />
        </div>
        <div>
          <h2 className="text-xl font-semibold text-white">Microservice Integrations</h2>
          <p className="text-sm text-slate-400">Connect your internal tools and ITSM platforms to Aether's AI engine.</p>
        </div>
      </div>

      <div className="space-y-8">
        
        {/* GITHUB SECTION */}
        <div className="bg-slate-950/50 border border-slate-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <GitBranch className="text-emerald-400" size={20} />
              <h3 className="text-lg font-medium text-white">GitHub Integration</h3>
            </div>
            <button 
              onClick={handleTestConnection}
              disabled={testLoading || !settings.github_token || isEditing}
              className="bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-400 border border-emerald-500/30 px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-2 disabled:opacity-50"
            >
              {testLoading ? <Loader2 size={16} className="animate-spin" /> : <Link2 size={16} />}
              Test Connection
            </button>
            <button 
              onClick={() => isEditing ? handleSaveSettings() : setIsEditing(true)}
              className="bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-2"
            >
              {isEditing ? 'Save' : 'Edit'}
            </button>
          </div>
          
          <p className="text-sm text-slate-400 mb-6">
            Aether is configured to escalate unresolvable tickets to your GitHub repository automatically.
          </p>
          
          {testResult && (
            <div className={`p-4 rounded-lg mb-6 text-sm flex items-center gap-2 ${testResult.status === 'success' ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400' : 'bg-rose-500/10 border border-rose-500/20 text-rose-400'}`}>
              {testResult.status === 'success' ? <CheckCircle2 size={16} /> : <div className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />}
              {testResult.message}
            </div>
          )}

          <div className="grid grid-cols-2 gap-6">
            <div>
              <label className="text-xs text-slate-500 font-medium mb-1.5 block">Repository</label>
              {isEditing ? (
                <div className="flex gap-2">
                  <input 
                    type="text" 
                    value={editForm.github_user}
                    onChange={(e) => setEditForm({...editForm, github_user: e.target.value})}
                    className="w-1/2 bg-slate-900 border border-emerald-500/50 rounded-lg px-3 py-2.5 text-slate-300 text-sm focus:outline-none"
                    placeholder="User/Org"
                  />
                  <span className="text-slate-500 self-center">/</span>
                  <input 
                    type="text" 
                    value={editForm.github_repo_name}
                    onChange={(e) => setEditForm({...editForm, github_repo_name: e.target.value})}
                    className="w-1/2 bg-slate-900 border border-emerald-500/50 rounded-lg px-3 py-2.5 text-slate-300 text-sm focus:outline-none"
                    placeholder="Repo name"
                  />
                </div>
              ) : (
                <div className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-slate-300 font-mono text-sm opacity-80">
                  {settings.github_repo || 'Not configured'}
                </div>
              )}
            </div>
            <div>
              <label className="text-xs text-slate-500 font-medium mb-1.5 block">Access Token</label>
              {isEditing ? (
                <div className="relative">
                  <input
                    type={showToken ? 'text' : 'password'}
                    value={editForm.github_token}
                    onChange={(e) => setEditForm({...editForm, github_token: e.target.value})}
                    className="w-full bg-slate-900 border border-emerald-500/50 rounded-lg pl-4 pr-10 py-2.5 text-slate-300 text-sm focus:outline-none"
                    placeholder={settings.github_token ? 'Leave blank to keep the current token' : 'ghp_...'}
                  />
                  <button
                    type="button"
                    onClick={() => setShowToken(v => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                    tabIndex={-1}
                  >
                    {showToken ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              ) : (
                <div className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-2.5 text-slate-300 font-mono text-sm opacity-80">
                  {settings.github_token ? 'ghp_••••••••••••••••••••' : 'Not configured'}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* API KEY SECTION */}
        <div className="bg-slate-950/50 border border-slate-800 rounded-xl p-6 opacity-50">
          <div className="flex items-center gap-3 mb-4">
            <KeyRound className="text-emerald-400" size={20} />
            <h3 className="text-lg font-medium text-white">Aether API Key</h3>
          </div>
          <p className="text-sm text-slate-400 mb-4">
            Use this key to authenticate requests from your microservice to Aether's endpoints (e.g. <code className="text-indigo-300 bg-indigo-500/10 px-1 py-0.5 rounded">POST /api/webhook/ticket</code>).
          </p>
          <div className="flex items-center gap-2">
            <input 
              type="text" 
              readOnly 
              value={settings.api_key || 'No API Key generated'} 
              className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-emerald-400 font-mono text-sm focus:outline-none"
            />
            <button 
              onClick={handleCopy}
              className="bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2.5 rounded-lg transition-colors flex items-center gap-2"
            >
              {copied ? <CheckCircle2 size={18} className="text-emerald-400" /> : <Copy size={18} />}
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>

        {/* MONITORED SERVICES SECTION */}
        <div className="bg-slate-950/50 border border-slate-800 rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <Activity className="text-cyan-400" size={20} />
              <h3 className="text-lg font-medium text-white">Monitored Services</h3>
            </div>
            <button
              onClick={() => isEditingServices ? handleSaveServices() : setIsEditingServices(true)}
              className="bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-2"
            >
              {isEditingServices ? 'Save' : 'Edit'}
            </button>
          </div>
          <p className="text-sm text-slate-400 mb-6">
            Services the agent can healthcheck before assuming a "can't connect" report is a user-side issue.
          </p>

          <div className="space-y-3">
            {services.length === 0 && !isEditingServices && (
              <div className="text-sm text-slate-500 italic">No services configured.</div>
            )}
            {services.map((s, i) => (
              <div key={i} className="flex gap-2">
                <input
                  type="text"
                  readOnly={!isEditingServices}
                  value={s.name}
                  onChange={(e) => updateService(i, 'name', e.target.value)}
                  placeholder="Service name"
                  className="w-1/3 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-slate-300 text-sm focus:outline-none disabled:opacity-80"
                />
                <input
                  type="text"
                  readOnly={!isEditingServices}
                  value={s.url}
                  onChange={(e) => updateService(i, 'url', e.target.value)}
                  placeholder="https://..."
                  className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-slate-300 font-mono text-sm focus:outline-none disabled:opacity-80"
                />
                {isEditingServices && (
                  <button onClick={() => removeService(i)} className="text-rose-400 hover:text-rose-300 px-2">
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
            ))}
            {isEditingServices && (
              <button onClick={addService} className="text-cyan-400 hover:text-cyan-300 text-sm flex items-center gap-1 mt-2">
                <Plus size={16} /> Add service
              </button>
            )}
          </div>
        </div>

        {/* WEBHOOK SECTION */}
        <div className="bg-slate-950/50 border border-slate-800 rounded-xl p-6">
          <div className="flex items-center gap-3 mb-4">
            <Webhook className="text-cyan-400" size={20} />
            <h3 className="text-lg font-medium text-white">Resolution Webhook</h3>
          </div>
          <p className="text-sm text-slate-400 mb-4">
            Aether will send HTTP POST requests to this URL when an autonomous action succeeds or fails.
          </p>
          <input 
            type="text" 
            readOnly 
            value={settings.webhook_url || 'Not configured'} 
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-300 text-sm focus:outline-none opacity-80"
          />
        </div>
        
      </div>
    </div>
  );
}
