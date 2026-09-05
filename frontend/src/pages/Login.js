import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Logo } from "@/components/Logo";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { AuthBrandPanel } from "@/components/AuthBrandPanel";

export default function Login() {
  const { loginWithToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // Arriving from a Care Circle invite link (InviteClaim.js's "Already have
  // an account? Log in" CTA) pre-fills the invited email and, after a
  // successful login, sends the person back to /invite/:token to finish
  // accepting instead of dropping them on the dashboard. Only an in-app
  // relative path is honored — never an absolute/external URL.
  const prefillEmail = searchParams.get("email") || "";
  const redirectTo = searchParams.get("redirect") || "";
  const isSafeRedirect = redirectTo.startsWith("/") && !redirectTo.startsWith("//");
  const [email, setEmail] = useState(prefillEmail);
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { data } = await api.post("/auth/login", { email, password });
      loginWithToken(data.access_token, data.refresh_token, data.user);
      toast.success(`Welcome back, ${data.user.name.split(" ")[0]}`);
      if (isSafeRedirect) navigate(redirectTo);
      else if (data.user.role === "admin") navigate("/admin");
      else navigate(data.user.onboarding_complete ? "/dashboard" : "/onboarding");
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-warm-cream">
      <AuthBrandPanel
        headline="Welcome back to their care circle."
        subtext="Your parents are one login away from another warm day. 💛"
        footer="Care that reaches home, every single day."
      />

      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <Link to="/" className="lg:hidden flex items-center justify-center mb-8">
            <Logo size={36} />
          </Link>
          <h1 className="font-display text-3xl font-semibold text-ayana-text">Log in</h1>
          <p className="mt-2 text-ayana-secondary">Continue caring from afar.</p>

          <form onSubmit={submit} className="mt-8 space-y-4" data-testid="login-form">
            <div>
              <label className="text-sm font-medium text-ayana-text">Email</label>
              <input
                type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                data-testid="login-email" placeholder="you@example.com"
                className="mt-1.5 w-full px-4 py-3 rounded-xl border border-ayana-line bg-white text-ayana-text focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-ayana-text">Password</label>
              <input
                type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
                data-testid="login-password" placeholder="••••••••"
                className="mt-1.5 w-full px-4 py-3 rounded-xl border border-ayana-line bg-white text-ayana-text focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition"
              />
            </div>
            <div className="flex justify-end -mt-1">
              <Link to="/forgot-password" className="text-sm text-ayana-bright font-medium hover:underline" data-testid="login-forgot">Forgot password?</Link>
            </div>
            {error && <p className="text-sm text-red-600" data-testid="login-error">{error}</p>}
            <button
              type="submit" disabled={loading} data-testid="login-submit"
              className="w-full btn-saffron flex items-center justify-center gap-2 px-6 py-3.5 rounded-full font-semibold disabled:opacity-60"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />} Log in
            </button>
          </form>

          <p className="mt-6 text-sm text-ayana-secondary text-center">
            New here?{" "}
            <Link to="/signup" className="text-ayana-bright font-semibold hover:underline" data-testid="login-to-signup">Create an account</Link>
          </p>
        </div>
      </div>
    </div>
  );
}