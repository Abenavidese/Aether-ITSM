import { useState } from 'react';
import { User, Users, Link2, Database } from 'lucide-react';
import { IntegrationPanel } from '../components/IntegrationPanel';
import { ProfilePanel } from '../components/ProfilePanel';
import { TeamManagementPanel } from '../components/TeamManagementPanel';
import { KnowledgeBasePanel } from '../components/KnowledgeBasePanel';

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<'profile' | 'connections' | 'team' | 'knowledge'>('team');

  return (
    <div className="max-w-5xl mx-auto">
      <header className="mb-8 border-b border-slate-800 pb-4">
        <h1 className="text-3xl font-bold text-white mb-2">Platform Settings</h1>
        <p className="text-slate-400 text-sm">Manage your Aether profile and external integrations.</p>
        
        <div className="flex gap-6 mt-8">
          <button 
            onClick={() => setActiveTab('profile')}
            className={`flex items-center gap-2 pb-2 px-1 border-b-2 font-medium transition-colors ${activeTab === 'profile' ? 'border-indigo-500 text-indigo-400' : 'border-transparent text-slate-500 hover:text-slate-300'}`}
          >
            <User size={18} /> Profile Configurations
          </button>
          <button
            onClick={() => setActiveTab('team')}
            className={`flex items-center gap-2 pb-2 px-1 border-b-2 font-medium transition-colors ${activeTab === 'team' ? 'border-indigo-500 text-indigo-400' : 'border-transparent text-slate-500 hover:text-slate-300'}`}
          >
            <Users size={18} /> Team Management
          </button>
          <button
            onClick={() => setActiveTab('knowledge')}
            className={`flex items-center gap-2 pb-2 px-1 border-b-2 font-medium transition-colors ${activeTab === 'knowledge' ? 'border-indigo-500 text-indigo-400' : 'border-transparent text-slate-500 hover:text-slate-300'}`}
          >
            <Database size={18} /> Knowledge Base
          </button>
          <button
            onClick={() => setActiveTab('connections')}
            className={`flex items-center gap-2 pb-2 px-1 border-b-2 font-medium transition-colors ${activeTab === 'connections' ? 'border-indigo-500 text-indigo-400' : 'border-transparent text-slate-500 hover:text-slate-300'}`}
          >
            <Link2 size={18} /> Connection Configurations
          </button>
        </div>
      </header>

      {activeTab === 'profile' ? (
        <ProfilePanel />
      ) : activeTab === 'team' ? (
        <TeamManagementPanel />
      ) : activeTab === 'knowledge' ? (
        <KnowledgeBasePanel />
      ) : (
        <IntegrationPanel />
      )}
    </div>
  );
}
