import { useState, useEffect } from 'react';
import { User, Building2, BrainCircuit, Edit2, Save } from 'lucide-react';
import { config } from '../../../config';
import { useAuth } from '../../../context/AuthContext';

export function ProfilePanel() {
  const { token } = useAuth();
  const [settings, setSettings] = useState<any>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState({ 
    user_full_name: '', 
    company_name: '',
    llm_engine: ''
  });

  const fetchSettings = async () => {
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/settings`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setSettings(data);
        setEditForm({ 
          user_full_name: data.user_full_name || '', 
          company_name: data.company_name || '',
          llm_engine: data.llm_engine || ''
        });
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchSettings();
  }, [token]);

  const handleSaveSettings = async () => {
    try {
      const res = await fetch(`${config.API_BASE_URL}/tenant/settings`, {
        method: 'PUT',
        headers: { 
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(editForm)
      });
      if (res.ok) {
        setIsEditing(false);
        fetchSettings(); // Refresh
      }
    } catch (err) {
      console.error(err);
    }
  };

  if (!settings) return <div className="p-8 text-center text-slate-500 animate-pulse">Loading Profile...</div>;

  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-8 shadow-xl">
      <div className="flex items-center justify-between mb-8 pb-6 border-b border-slate-800">
        <div className="flex items-center gap-4">
          <div className="bg-indigo-500/20 p-4 rounded-xl text-indigo-400">
            <User size={24} />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white">Profile Configurations</h2>
            <p className="text-sm text-slate-400">Manage your tenant profile and core AI settings.</p>
          </div>
        </div>
        <button 
          onClick={() => isEditing ? handleSaveSettings() : setIsEditing(true)}
          className="bg-slate-800 hover:bg-slate-700 text-slate-300 px-4 py-2 rounded-lg text-sm transition-colors flex items-center gap-2"
        >
          {isEditing ? 'Save Profile' : 'Edit Profile'}
        </button>
      </div>

      <div className="space-y-6 max-w-2xl">
        
        {/* Administrator Name */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <User className="text-indigo-400" size={16} />
            <label className="text-sm font-medium text-slate-300">Administrator Name</label>
          </div>
          {isEditing ? (
            <input 
              type="text" 
              value={editForm.user_full_name}
              onChange={(e) => setEditForm({...editForm, user_full_name: e.target.value})}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-indigo-500 transition-colors"
            />
          ) : (
            <div className="bg-slate-950/50 border border-slate-800 rounded-lg px-4 py-2.5 text-slate-300 text-sm">
              {settings.user_full_name || 'Not provided'}
            </div>
          )}
        </div>

        {/* Company Name */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Building2 className="text-cyan-400" size={16} />
            <label className="text-sm font-medium text-slate-300">Company Name</label>
          </div>
          {isEditing ? (
            <input 
              type="text" 
              value={editForm.company_name}
              onChange={(e) => setEditForm({...editForm, company_name: e.target.value})}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-cyan-500 transition-colors"
            />
          ) : (
            <div className="bg-slate-950/50 border border-slate-800 rounded-lg px-4 py-2.5 text-slate-300 text-sm">
              {settings.company_name || 'Not provided'}
            </div>
          )}
        </div>

        {/* LLM Engine */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <BrainCircuit className="text-emerald-400" size={16} />
            <label className="text-sm font-medium text-slate-300">AI LLM Engine</label>
          </div>
          {isEditing ? (
            <select
              value={editForm.llm_engine}
              onChange={(e) => setEditForm({...editForm, llm_engine: e.target.value})}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2.5 text-slate-100 text-sm focus:outline-none focus:border-emerald-500 transition-colors appearance-none"
            >
              <option value="nemotron-nano">NVIDIA Nemotron Nano</option>
              <option value="gpt-4o">OpenAI GPT-4o</option>
            </select>
          ) : (
            <div className="bg-slate-950/50 border border-slate-800 rounded-lg px-4 py-2.5 text-emerald-300 font-medium text-sm">
              {settings.llm_engine === 'nemotron-nano' ? 'NVIDIA Nemotron Nano' : 
               settings.llm_engine === 'gpt-4o' ? 'OpenAI GPT-4o' : 
               settings.llm_engine || 'nemotron-nano'}
            </div>
          )}
          <p className="text-xs text-slate-500 mt-2">
            The core engine used for ticket classification and autonomous resolution.
          </p>
        </div>

      </div>
    </div>
  );
}
