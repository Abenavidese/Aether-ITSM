import { Routes, Route, Navigate, useLocation, Outlet } from 'react-router-dom';
import { PublicRoute } from './layouts/PublicRoute';
import { DashboardLayout } from './layouts/DashboardLayout';
import { LoginPage, RegisterPage, ForgotPasswordPage } from '../features/auth';
import { EmployeePortalPage } from '../features/portal';
import { AdminDashboardPage, SettingsPage } from '../features/admin';
import { OnboardingPage } from '../features/onboarding/index';
import { useAuth } from '../context/AuthContext';

// Basic wrapper just to enforce auth and onboarding state, without the sidebar
function RequireAuth({ children, requireOnboarding = false }: { children: JSX.Element, requireOnboarding?: boolean }) {
  const { token, user } = useAuth();
  const location = useLocation();
  
  if (!token) return <Navigate to="/login" replace />;

  if (user && user.role === 'superadmin') {
    // If onboarding is incomplete, force them to /onboarding
    if (user.onboarding_completed === 'false' && location.pathname !== '/onboarding') {
      return <Navigate to="/onboarding" replace />;
    }
    // If onboarding IS complete, don't let them on the /onboarding page
    if (user.onboarding_completed !== 'false' && location.pathname === '/onboarding') {
      return <Navigate to="/admin" replace />;
    }
  }

  return children;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={
        <PublicRoute>
          <LoginPage />
        </PublicRoute>
      } />
      <Route path="/forgot-password" element={
        <PublicRoute>
          <ForgotPasswordPage />
        </PublicRoute>
      } />
      <Route path="/register" element={
        <PublicRoute>
          <RegisterPage />
        </PublicRoute>
      } />
      <Route path="/" element={
        <DashboardLayout>
          <EmployeePortalPage />
        </DashboardLayout>
      } />
      <Route path="/admin" element={
        <RequireAuth>
          <DashboardLayout allowedRoles={['superadmin', 'admin']}>
            <Outlet />
          </DashboardLayout>
        </RequireAuth>
      }>
        <Route index element={<AdminDashboardPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="/onboarding" element={
        <RequireAuth>
          <OnboardingPage />
        </RequireAuth>
      } />
    </Routes>
  );
}
