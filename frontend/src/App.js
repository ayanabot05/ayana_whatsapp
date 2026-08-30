import "@/App.css";
import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/context/AuthContext";
import { LanguageProvider } from "@/context/LanguageContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";

// Created at module level so it's stable across re-renders and HMR.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,       // 30 s — don't refetch too aggressively
      retry: 1,                // one retry on network errors
      refetchOnWindowFocus: false, // avoid surprise refetches when switching tabs
    },
  },
});

// Route-level code splitting: each page (and whatever it pulls in — e.g. Landing's
// Three.js scene) ships as its own chunk instead of all bundling into main.js.
// Login/Signup stay eager since they're the most common first paint after Landing.
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";
import Landing from "@/pages/Landing";

const Onboarding = lazy(() => import("@/pages/Onboarding"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Activation = lazy(() => import("@/pages/Activation"));
const Admin = lazy(() => import("@/pages/Admin"));
const InviteClaim = lazy(() => import("@/pages/InviteClaim"));
const PaymentSuccess = lazy(() => import("@/pages/PaymentReturn").then((m) => ({ default: m.PaymentSuccess })));
const PaymentCancel = lazy(() => import("@/pages/PaymentReturn").then((m) => ({ default: m.PaymentCancel })));

// Legal.js has named exports, not a default — React.lazy needs a default,
// so map each one. All four still share a single "Legal" chunk.
const Privacy = lazy(() => import("@/pages/Legal").then((m) => ({ default: m.Privacy })));
const Terms = lazy(() => import("@/pages/Legal").then((m) => ({ default: m.Terms })));
const Disclaimer = lazy(() => import("@/pages/Legal").then((m) => ({ default: m.Disclaimer })));
const DataDeletion = lazy(() => import("@/pages/Legal").then((m) => ({ default: m.DataDeletion })));

function PageFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <Loader2 className="w-8 h-8 animate-spin text-ayana-primary" />
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
    <div className="App">
      <AuthProvider>
        <LanguageProvider>
        <BrowserRouter>
          <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/login" element={<Login />} />
              <Route path="/signup" element={<Signup />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route path="/terms" element={<Terms />} />
              <Route path="/disclaimer" element={<Disclaimer />} />
              <Route path="/data-deletion" element={<DataDeletion />} />
              <Route path="/onboarding" element={<ProtectedRoute><Onboarding /></ProtectedRoute>} />
              <Route path="/activation" element={<ProtectedRoute><Activation /></ProtectedRoute>} />
              <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
              <Route path="/admin" element={<ProtectedRoute adminOnly><Admin /></ProtectedRoute>} />
              {/* Public invite claim — works for logged-in and new users */}
              <Route path="/invite/:token" element={<InviteClaim />} />
              <Route path="/payment/success" element={<PaymentSuccess />} />
              <Route path="/payment/cancel" element={<PaymentCancel />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
        </LanguageProvider>
        <Toaster position="top-center" richColors />
      </AuthProvider>
    </div>
    </QueryClientProvider>
  );
}

export default App;