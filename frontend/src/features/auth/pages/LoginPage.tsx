import { AuthLayout } from '../../../app/layouts/AuthLayout';
import { LoginForm } from '../components/LoginForm';

export function LoginPage() {
  return (
    <AuthLayout
      headline={<>The Future of <br/><span className="bg-gradient-to-r from-indigo-400 to-cyan-300 bg-clip-text text-transparent">Autonomous IT.</span></>}
      subtext="Empower your workforce with instant, AI-driven support. Aether ITSM integrates seamlessly with your infrastructure to deflect L1 tickets and govern L3 operations."
    >
      <LoginForm />
    </AuthLayout>
  );
}
