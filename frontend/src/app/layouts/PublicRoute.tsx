import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

export function PublicRoute({ children }: { children: ReactNode }) {
  const { token } = useAuth();
  if (token) return <Navigate to="/" replace />;
  return children;
}
