import { useState } from 'react';
import { config } from '../../../config';

interface RegisterFormState {
  // Step 1: Account
  fullName: string;
  email: string;
  password: string;
  confirmPassword: string;
  // Step 2: Organization
  companyName: string;
  companySize: string;
  industry: string;
  // Step 3: Personalization
  jobTitle: string;
  currentTool: string;
  primaryGoal: string;
}

interface UseRegisterFormReturn {
  form: RegisterFormState;
  step: number;
  error: string;
  shakeKey: number;
  loading: boolean;
  showPassword: boolean;
  setField: <K extends keyof RegisterFormState>(key: K, value: RegisterFormState[K]) => void;
  setShowPassword: (show: boolean) => void;
  handleNextStep: () => void;
  handlePrevStep: () => void;
  handleSubmit: (e: React.FormEvent, onSuccess: (token: string) => void) => Promise<void>;
  isStepValid: (stepNumber: number) => boolean;
}

const isPasswordValid = (pass: string) => {
  return /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&._-])[A-Za-z\d@$!%*?&._-]+$/.test(pass) && pass.length >= 8;
};

export function useRegisterForm(): UseRegisterFormReturn {
  const [step, setStep] = useState(1);
  const [error, setError] = useState('');
  const [shakeKey, setShakeKey] = useState(0);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const [form, setForm] = useState<RegisterFormState>({
    fullName: '',
    email: '',
    password: '',
    confirmPassword: '',
    companyName: '',
    companySize: '',
    industry: '',
    jobTitle: '',
    currentTool: '',
    primaryGoal: '',
  });

  const setField = <K extends keyof RegisterFormState>(key: K, value: RegisterFormState[K]) => {
    setForm(prev => ({ ...prev, [key]: value }));
  };

  const triggerError = (msg: string) => {
    setError(msg);
    setShakeKey(prev => prev + 1);
  };

  const isStepValid = (stepNumber: number) => {
    if (stepNumber === 1) return !!(form.fullName && form.email && form.password && form.confirmPassword);
    if (stepNumber === 2) return !!(form.companyName && form.companySize && form.industry);
    if (stepNumber === 3) return !!(form.jobTitle && form.currentTool && form.primaryGoal);
    return false;
  };

  const handleNextStep = () => {
    setError('');
    if (step === 1) {
      if (form.password !== form.confirmPassword) return triggerError("Passwords do not match.");
      if (!isPasswordValid(form.password)) return triggerError("Password must be 8+ chars and contain at least 1 uppercase, 1 lowercase, 1 number, and 1 symbol.");
    }
    if (step < 3) setStep(s => s + 1);
  };

  const handlePrevStep = () => {
    setError('');
    setStep(s => s - 1);
  };

  const handleSubmit = async (e: React.FormEvent, onSuccess: (token: string) => void) => {
    e.preventDefault();
    if (step !== 3) {
      handleNextStep();
      return;
    }

    setError('');
    setLoading(true);

    try {
      const payload = {
        full_name: form.fullName,
        email: form.email,
        password: form.password,
        company_name: form.companyName,
        company_size: form.companySize,
        industry: form.industry,
        job_title: form.jobTitle,
        current_tool: form.currentTool,
        primary_goal: form.primaryGoal,
      };

      const registerRes = await fetch(`${config.API_BASE_URL}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!registerRes.ok) {
        const errorData = await registerRes.json();
        throw new Error(errorData.detail || 'Registration failed');
      }

      // Auto-Login
      const loginRes = await fetch(`${config.API_BASE_URL}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: form.email, password: form.password }),
      });

      if (!loginRes.ok) throw new Error('Registered successfully, but auto-login failed.');

      const data = await loginRes.json();
      onSuccess(data.access_token);
    } catch (err: any) {
      setError(err.message || 'An unexpected error occurred');
    } finally {
      setLoading(false);
    }
  };

  return {
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
  };
}
