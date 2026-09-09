import { ArrowRight, ArrowLeft, Sparkles } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../../context/AuthContext';
import { useRegisterForm } from '../hooks/useRegisterForm';
import { StepAccount } from './StepAccount';
import { StepOrganization } from './StepOrganization';
import { StepPersonalize } from './StepPersonalize';

export function RegisterWizard() {
  const { login } = useAuth();
  const {
    form,
    step,
    error,
    shakeKey,
    loading,
    showPassword,
    setField,
    setShowPassword,
    handleNextStep,
    handlePrevStep,
    handleSubmit,
    isStepValid,
  } = useRegisterForm();

  return (
    <>
      {/* Progress Indicator */}
      <div className="flex gap-2 mb-12">
        {[1, 2, 3].map((i) => (
          <div key={i} className={`h-1.5 rounded-full flex-1 transition-all duration-500 ${step >= i ? 'bg-indigo-500 shadow-[0_0_10px_rgba(99,102,241,0.5)]' : 'bg-slate-800'}`} />
        ))}
      </div>

      <div className="mb-8">
        <h2 className="text-3xl font-semibold text-white mb-2">
          {step === 1 && "Account Details"}
          {step === 2 && "Your Organization"}
          {step === 3 && "Personalize your setup"}
        </h2>
        <p className="text-slate-400 text-sm">
          {step === 1 && "Let's start with the basics to secure your account."}
          {step === 2 && "Tell us about your company to tailor your workspace."}
          {step === 3 && "Help us configure the AI for your specific use case."}
        </p>
      </div>

      {error && (
        <div key={shakeKey} className="animate-shake bg-rose-500/10 border border-rose-500/20 text-rose-400 p-4 rounded-xl text-sm mb-6 flex items-center gap-3">
          <div className="w-1.5 h-1.5 bg-rose-500 rounded-full animate-pulse flex-shrink-0" />
          <p>{error}</p>
        </div>
      )}

      <form onSubmit={(e) => handleSubmit(e, login)} className="space-y-5 relative">
        
        {step === 1 && (
          <StepAccount
            fullName={form.fullName}
            email={form.email}
            password={form.password}
            confirmPassword={form.confirmPassword}
            showPassword={showPassword}
            onFieldChange={(field, value) => setField(field as any, value)}
            onTogglePassword={() => setShowPassword(!showPassword)}
          />
        )}

        {step === 2 && (
          <StepOrganization
            companyName={form.companyName}
            companySize={form.companySize}
            industry={form.industry}
            onFieldChange={(field, value) => setField(field as any, value)}
          />
        )}

        {step === 3 && (
          <StepPersonalize
            jobTitle={form.jobTitle}
            currentTool={form.currentTool}
            primaryGoal={form.primaryGoal}
            onFieldChange={(field, value) => setField(field as any, value)}
          />
        )}

        <div className="flex gap-4 pt-4">
          {step > 1 && (
            <button type="button" onClick={handlePrevStep} className="w-1/3 bg-slate-800 hover:bg-slate-700 text-white font-semibold py-3.5 rounded-xl transition-all flex items-center justify-center gap-2">
              <ArrowLeft size={18} /> Back
            </button>
          )}
          
          {step < 3 ? (
            <button 
              type="button" 
              onClick={handleNextStep} 
              disabled={!isStepValid(step)}
              className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3.5 rounded-xl transition-all flex items-center justify-center gap-2 shadow-[0_0_15px_rgba(79,70,229,0.3)] hover:shadow-[0_0_25px_rgba(79,70,229,0.5)] disabled:opacity-50 disabled:shadow-none disabled:hover:bg-indigo-600 disabled:cursor-not-allowed"
            >
              Continue <ArrowRight size={18} />
            </button>
          ) : (
            <button 
              type="submit" 
              disabled={loading || !isStepValid(step)} 
              className="flex-1 bg-cyan-600 hover:bg-cyan-500 text-white font-semibold py-3.5 rounded-xl transition-all flex items-center justify-center gap-2 disabled:opacity-50 shadow-[0_0_15px_rgba(8,145,178,0.3)] hover:shadow-[0_0_25px_rgba(8,145,178,0.5)] disabled:shadow-none disabled:hover:bg-cyan-600 disabled:cursor-not-allowed"
            >
              {loading ? 'Setting up tenant...' : 'Create Account'}
              {!loading && <Sparkles size={18} />}
            </button>
          )}
        </div>
      </form>

      <div className="mt-8 text-center">
        <p className="text-sm text-slate-400">
          Already have an account?{' '}
          <Link to="/login" className="text-indigo-400 hover:text-indigo-300 font-medium transition-colors">
            Sign in instead
          </Link>
        </p>
      </div>
    </>
  );
}
