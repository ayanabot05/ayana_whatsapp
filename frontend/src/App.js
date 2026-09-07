import "@/App.css";
import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/sonner";
import { Analytics } from "@vercel/analytics/react";

import { AuthProvider } from "@/context/AuthContext";
import { LanguageProvider } from "@/context/LanguageContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";

// Created at module level so it's stable across re-renders and HMR.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000, // 30 seconds — don't refetch too aggressively
      retry: 1, // One retry on network errors
      refetchOnWindowFocus: false, // Avoid surprise refetches when switching tabs
    },
  },
});

// --------------------------------------------------
// Eager-loaded pages
// --------------------------------------------------
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";
import ForgotPassword from "@/pages/ForgotPassword";
import Landing from "@/pages/Landing";

// --------------------------------------------------
// Lazy-loaded pages
// --------------------------------------------------
const Onboarding = lazy(() => import("@/pages/Onboarding"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Activation = lazy(() => import("@/pages/Activation"));
const Admin = lazy(() => import("@/pages/Admin"));
const InviteClaim = lazy(() => import("@/pages/InviteClaim"));

const PaymentSuccess = lazy(() =>
  import("@/pages/PaymentReturn").then((m) => ({
    default: m.PaymentSuccess,
  }))
);

const PaymentCancel = lazy(() =>
  import("@/pages/PaymentReturn").then((m) => ({
    default: m.PaymentCancel,
  }))
);

// --------------------------------------------------
// Legal pages
// Legal.js uses named exports, so map them to default
// exports for React.lazy.
// --------------------------------------------------
const Privacy = lazy(() =>
  import("@/pages/Legal").then((m) => ({
    default: m.Privacy,
  }))
);

const Terms = lazy(() =>
  import("@/pages/Legal").then((m) => ({
    default: m.Terms,
  }))
);

const Disclaimer = lazy(() =>
  import("@/pages/Legal").then((m) => ({
    default: m.Disclaimer,
  }))
);

const DataDeletion = lazy(() =>
  import("@/pages/Legal").then((m) => ({
    default: m.DataDeletion,
  }))
);

// --------------------------------------------------
// Loading fallback for lazy-loaded pages
// --------------------------------------------------
function PageFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <Loader2 className="w-8 h-8 animate-spin text-ayana-primary" />
    </div>
  );
}

// --------------------------------------------------
// Main App
// --------------------------------------------------
function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <div className="App">
        <AuthProvider>
          <LanguageProvider>
            <BrowserRouter>
              <Suspense fallback={<PageFallback />}>
                <Routes>

                  {/* Public routes */}
                  <Route path="/" element={<Landing />} />

                  <Route path="/login" element={<Login />} />

                  <Route path="/signup" element={<Signup />} />

                  <Route
                    path="/forgot-password"
                    element={<ForgotPassword />}
                  />

                  {/* Legal pages */}
                  <Route path="/privacy" element={<Privacy />} />

                  <Route path="/terms" element={<Terms />} />

                  <Route
                    path="/disclaimer"
                    element={<Disclaimer />}
                  />

                  <Route
                    path="/data-deletion"
                    element={<DataDeletion />}
                  />

                  {/* Protected user routes */}
                  <Route
                    path="/onboarding"
                    element={
                      <ProtectedRoute>
                        <Onboarding />
                      </ProtectedRoute>
                    }
                  />

                  <Route
                    path="/activation"
                    element={
                      <ProtectedRoute>
                        <Activation />
                      </ProtectedRoute>
                    }
                  />

                  <Route
                    path="/dashboard"
                    element={
                      <ProtectedRoute>
                        <Dashboard />
                      </ProtectedRoute>
                    }
                  />

                  {/* Protected admin route */}
                  <Route
                    path="/admin"
                    element={
                      <ProtectedRoute adminOnly>
                        <Admin />
                      </ProtectedRoute>
                    }
                  />

                  {/* Public invite claim */}
                  {/* Works for both logged-in and new users */}
                  <Route
                    path="/invite/:token"
                    element={<InviteClaim />}
                  />

                  {/* Payment routes */}
                  <Route
                    path="/payment/success"
                    element={<PaymentSuccess />}
                  />

                  <Route
                    path="/payment/cancel"
                    element={<PaymentCancel />}
                  />

                </Routes>
              </Suspense>
            </BrowserRouter>
          </LanguageProvider>

          {/* Toast notifications */}
          <Toaster
            position="top-center"
            richColors
          />
        </AuthProvider>

        {/* Vercel Analytics */}
        <Analytics />
      </div>
    </QueryClientProvider>
  );
}

export default App;