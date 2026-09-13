import { Routes, Route, Navigate, useLocation, Outlet } from 'react-router-dom';
import type { ReactNode } from 'react';
import { PublicRoute } from './layouts/PublicRoute';
import { DashboardLayout } from './layouts/DashboardLayout';
import { LoginPage, RegisterPage, ForgotPasswordPage } from '../features/auth';
import { EmployeePortalPage } from '../features/portal';
import { AdminDashboardPage, SettingsPage } from '../features/admin';
import { OnboardingPage } from '../features/onboarding/index';
import { useAuth } from '../context/AuthContext';

// Basic wrapper just to enforce auth and onboarding state, without the sidebar
function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <div className="p-8 text-center text-slate-500 animate-pulse">Loading...</div>;
  if (!user) return <Navigate to="/login" replace />;

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

function RequireRole({ children, roles }: { children: ReactNode, roles: string[] }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) {
    return <Navigate to="/" replace />;
  }
  return children;
}

function RootRedirect() {
  const { user } = useAuth();
  if (user && (user.role === 'admin' || user.role === 'superadmin')) {
    return <Navigate to="/admin" replace />;
  }
  return <Navigate to="/chat" replace />;
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
        <RequireAuth>
          <RootRedirect />
        </RequireAuth>
      } />
      <Route path="/chat" element={
        <DashboardLayout>
          <EmployeePortalPage />
        </DashboardLayout>
      } />
      <Route path="/admin" element={
        <RequireAuth>
          <DashboardLayout>
            <Outlet />
          </DashboardLayout>
        </RequireAuth>
      }>
        <Route index element={<AdminDashboardPage />} />
        <Route path="settings" element={
          <RequireRole roles={['superadmin', 'admin']}>
            <SettingsPage />
          </RequireRole>
        } />
      </Route>
      <Route path="/onboarding" element={
        <RequireAuth>
          <OnboardingPage />
        </RequireAuth>
      } />
    </Routes>
  );
}
