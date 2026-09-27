import { useState } from 'react';
import { Sparkles, ArrowRight, ShieldCheck, KeyRound, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import { config } from '../../../config';

// Models are platform configuration (see Settings > Profile), not a
// per-tenant choice, so onboarding is just the agreements + GitHub.
const TOTAL_STEPS = 2;

export function OnboardingPage() {
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  
  // Settings State
  const [githubToken, setGithubToken] = useState('');
  const [githubUser, setGithubUser] = useState('');
  const [githubRepoName, setGithubRepoName] = useState('');

  const { login } = useAuth(); // We might need to refresh token to update onboarding_completed

  
  const handleComplete = async () => {
    setLoading(true);
    try {
      const response = await fetch(`${config.API_BASE_URL}/tenant/onboarding`, {
        method: 'POST',
        credentials: 'include',
        headers: { 
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          github_token: githubToken,
          github_repo: `${githubUser}/${githubRepoName}`
        })
      });

      if (!response.ok) throw new Error("Failed to save configuration");
      
      await response.json();
      
      // Refresh token so the new onboarding_completed status is updated
      login('/admin');
    } catch (err) {
      console.error(err);
      // Fallback
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0B1120] flex items-center justify-center p-8 font-sans relative overflow-hidden">
      {/* Ambient background */}
      <div className="absolute top-[-20%] right-[-10%] w-[60%] h-[60%] bg-indigo-600/10 blur-[150px] rounded-full pointer-events-none mix-blend-screen" />
      <div className="absolute bottom-[-10%] left-[-10%] w-[50%] h-[50%] bg-emerald-500/10 blur-[150px] rounded-full pointer-events-none mix-blend-screen" />

      <div className="max-w-2xl w-full bg-slate-900/80 border border-slate-800 rounded-2xl shadow-2xl backdrop-blur-xl relative z-10 overflow-hidden">
        
        {/* Progress Bar */}
        <div className="flex w-full h-1.5 bg-slate-800">
          <div className="bg-indigo-500 h-full transition-all duration-500" style={{ width: `${(step / TOTAL_STEPS) * 100}%` }} />
        </div>

        <div className="p-10 sm:p-12">
          {/* STEP 1: WELCOME & T&C */}
          {step === 1 && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <div className="w-16 h-16 bg-indigo-500/20 rounded-2xl flex items-center justify-center mb-6 border border-indigo-500/30">
                <ShieldCheck className="text-indigo-400" size={32} />
              </div>
              <h1 className="text-3xl font-bold text-white mb-4">Welcome to Aether ITSM</h1>
              <p className="text-slate-400 text-lg leading-relaxed mb-8">
                You are setting up the Command Center for your organization. Aether uses autonomous AI to resolve IT tickets and execute infrastructure actions. 
                Because of the power of this system, strict guardrails are enforced.
              </p>
              
              <div className="bg-slate-950/50 border border-slate-800 rounded-xl p-5 mb-8">
                <h3 className="text-slate-200 font-medium mb-3">Autonomy Cascade Agreements</h3>
                <ul className="space-y-3 text-sm text-slate-400">
                  <li className="flex gap-3"><CheckCircle2 size={18} className="text-emerald-500 shrink-0" /> I understand Aether will automatically resolve L1 and L2 tickets without human intervention.</li>
                  <li className="flex gap-3"><CheckCircle2 size={18} className="text-emerald-500 shrink-0" /> I agree that high-risk L3/L4 actions will require human approval via the dashboard.</li>
                  <li className="flex gap-3"><CheckCircle2 size={18} className="text-emerald-500 shrink-0" /> I will securely store my API keys and MCP credentials.</li>
                </ul>
              </div>

              <button 
                onClick={() => setStep(2)}
                className="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-4 rounded-xl transition-all shadow-[0_0_20px_rgba(79,70,229,0.3)] flex justify-center items-center gap-2"
              >
                I Accept & Continue <ArrowRight size={18} />
              </button>
            </div>
          )}

          {/* STEP 2: GITHUB INTEGRATION */}
          {step === 2 && (
            <div className="animate-in fade-in slide-in-from-right-4 duration-500">
              <div className="w-16 h-16 bg-emerald-500/20 rounded-2xl flex items-center justify-center mb-6 border border-emerald-500/30">
                <KeyRound className="text-emerald-400" size={32} />
              </div>
              <h1 className="text-3xl font-bold text-white mb-4">Connect Your Infrastructure</h1>
              <p className="text-slate-400 text-lg leading-relaxed mb-6">
                To allow Aether to escalate issues to your development team, provide a GitHub Personal Access Token (PAT) with write access to your repository.
              </p>
              
              <div className="space-y-5 mb-8">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-300">GitHub Personal Access Token</label>
                  <input 
                    type="password" 
                    value={githubToken} 
                    onChange={e => setGithubToken(e.target.value)}
                    placeholder="ghp_xxxxxxxxxxxx"
                    className="w-full bg-slate-950 border border-emerald-500/50 rounded-xl px-4 py-3 text-emerald-400 font-mono text-sm focus:outline-none focus:border-emerald-500 transition-colors"
                  />
                  <p className="text-xs text-slate-500">Must have 'repo' and 'write:discussion' scopes.</p>
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-300">GitHub Username or Organization</label>
                  <input 
                    type="text" 
                    value={githubUser}
                    onChange={e => setGithubUser(e.target.value)}
                    placeholder="e.g. microsoft or Abenavidese" 
                    className="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 placeholder-slate-600 focus:outline-none focus:border-indigo-500 transition-colors"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-sm font-medium text-slate-300">Repository Name</label>
                  <input 
                    type="text" 
                    value={githubRepoName}
                    onChange={e => setGithubRepoName(e.target.value)}
                    placeholder="e.g. core-ecommerce-api" 
                    className="w-full bg-slate-950 border border-slate-700 rounded-xl px-4 py-3 text-slate-100 placeholder-slate-600 focus:outline-none focus:border-indigo-500 transition-colors"
                  />
                  <p className="text-xs text-slate-500">
                    Target repo: <span className="font-mono text-indigo-400">{githubUser || 'username'}/{githubRepoName || 'repo'}</span>
                  </p>
                </div>
              </div>

              <button 
                onClick={handleComplete}
                disabled={loading || !githubToken || !githubUser || !githubRepoName}
                className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-4 rounded-xl transition-all shadow-[0_0_20px_rgba(16,185,129,0.3)] flex justify-center items-center gap-2 disabled:opacity-50"
              >
                {loading ? 'Initializing Tenant...' : 'Complete Setup & Enter Dashboard'}
                {!loading && <Sparkles size={18} />}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
