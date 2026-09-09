import { AuthLayout } from '../../../app/layouts/AuthLayout';
import { RegisterWizard } from '../components/RegisterWizard';

export function RegisterPage() {
  return (
    <AuthLayout
      headline={<>Build your <br/><span className="bg-gradient-to-r from-indigo-400 to-cyan-300 bg-clip-text text-transparent">Autonomous Hub.</span></>}
      subtext="Create your enterprise tenant in seconds. Instantly deploy AI agents to handle L1 tickets, govern operations, and scale your support desk effortlessly."
    >
      <RegisterWizard />
    </AuthLayout>
  );
}
