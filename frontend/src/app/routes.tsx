import { Routes, Route } from 'react-router-dom';
import { DashboardLayout } from './layouts/DashboardLayout';
import { PublicRoute } from './layouts/PublicRoute';
import { LoginPage, RegisterPage } from '../features/auth';
import { EmployeePortalPage } from '../features/portal';
import { AdminDashboardPage } from '../features/admin';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={
        <PublicRoute>
          <LoginPage />
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
        <DashboardLayout allowedRoles={['superadmin', 'admin']}>
          <AdminDashboardPage />
        </DashboardLayout>
      } />
    </Routes>
  );
}
