import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Loader2 } from "lucide-react";

export function ProtectedRoute({ children, adminOnly = false, deliveryOnly = false }) {
  const { user } = useAuth();
  const location = useLocation();

  if (user === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-ayana-bg">
        <Loader2 className="w-8 h-8 animate-spin text-ayana-primary" strokeWidth={1.5} />
      </div>
    );
  }
  if (!user) return <Navigate to={`/login?redirect=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  if (user.role === 'support' && !deliveryOnly) return <Navigate to="/worker" replace />;
  if (deliveryOnly && !['admin', 'support'].includes(user.role)) return <Navigate to="/dashboard" replace />;
  if (adminOnly && user.role !== "admin") return <Navigate to="/dashboard" replace />;
  return children;
}
