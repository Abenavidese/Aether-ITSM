import { AuthLayout } from '../../../app/layouts/AuthLayout';
import { ForgotPasswordForm } from '../components/ForgotPasswordForm';

export function ForgotPasswordPage() {
  return (
    <AuthLayout
      headline={<>Account <br/><span className="bg-gradient-to-r from-indigo-400 to-cyan-300 bg-clip-text text-transparent">Recovery.</span></>}
      subtext="Regain access to your enterprise tenant and continue managing your autonomous IT infrastructure seamlessly."
    >
      <ForgotPasswordForm />
    </AuthLayout>
  );
}
