import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Loader2, Heart } from "lucide-react";
import { Logo } from "@/components/Logo";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { AuthBrandPanel } from "@/components/AuthBrandPanel";

export default function Login() {
  const { loginWithToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const prefillEmail = searchParams.get("email") || "";
  const redirectTo = searchParams.get("redirect") || "";
  const isSafeRedirect = redirectTo.startsWith("/") &&!redirectTo.startsWith("//");
  const [email, setEmail] = useState(prefillEmail);
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const getFriendlyLoginError = (err) => {
    const status = err.response?.status;
    const detail = err.response?.data?.detail || "";
    const low = typeof detail === 'string'? detail.toLowerCase() : "";

    if (status === 404 || low.includes("no account found")) {
      return { message: "No account found with this email.", action: { label: "Create an account", to: `/signup?email=${encodeURIComponent(email)}` } };
    }
    if (status === 401 || low.includes("incorrect password")) {
      return { message: "Incorrect password.", action: { label: "Forgot password?", to: "/forgot-password" } };
    }
    return { message: typeof detail === 'string'? detail : "Something went wrong.", action: null };
  };

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { data } = await api.post("/auth/login", { email, password });
      loginWithToken(data.access_token, data.refresh_token, data.user);
      toast.success(`Welcome back, ${data.user.name.split(" ")[0]}! Your parents missed you. 💛`);
      if (isSafeRedirect) navigate(redirectTo);
      else if (data.user.role === "admin") navigate("/admin");
      else navigate(data.user.onboarding_complete? "/dashboard" : "/onboarding");
    } catch (err) {
      const friendly = getFriendlyLoginError(err);
      setError(friendly);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-warm-cream">
      <AuthBrandPanel
        headline="They're waiting to hear from you."
        subtext="Log in to check how your parents are doing today. One login, and you're right back in their day."
        emotionalQuote="You can't always call. But you can always care."
        footer="Ayana — helping you stay present, even from far away."
      />
      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <Link to="/" className="lg:hidden flex items-center justify-center mb-8"><Logo size={36} /></Link>

          <h1 className="font-display text-3xl font-semibold text-ayana-text">Welcome back</h1>
          <p className="mt-2 text-ayana-secondary text-[15px]">Your parents are one login away from another warm day. 💛</p>

          <form onSubmit={submit} className="mt-8 space-y-4" data-testid="login-form">
            <div>
              <label className="text-sm font-medium text-ayana-text">Email</label>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} data-testid="login-email" placeholder="you@example.com" className="mt-1.5 w-full px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-gold/40 focus:border-ayana-gold transition" />
            </div>
            <div>
              <label className="text-sm font-medium text-ayana-text">Password</label>
              <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} data-testid="login-password" placeholder="••••••••" className="mt-1.5 w-full px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-gold/40 focus:border-ayana-gold transition" />
            </div>
            <div className="flex justify-end -mt-1">
              <Link to="/forgot-password" className="text-sm text-ayana-gold font-medium hover:underline">Forgot password?</Link>
            </div>
            {error && (
              <p className="text-sm text-red-600" data-testid="login-error">
                {typeof error === 'string'? error : error.message}{" "}
                {error.action && <Link to={error.action.to} className="font-semibold underline">{error.action.label}</Link>}
              </p>
            )}
            <button type="submit" disabled={loading} className="w-full btn-saffron flex items-center justify-center gap-2 px-6 py-3.5 rounded-full font-semibold disabled:opacity-60">
              {loading && <Loader2 className="w-4 h-4 animate-spin" />} Log in to their care circle
            </button>
          </form>

          {/* Emotional nudge */}
          <div className="mt-6 flex items-center gap-2.5 bg-amber-50/80 border border-amber-200/50 rounded-xl px-4 py-3">
            <Heart className="w-4 h-4 text-ayana-gold shrink-0" fill="currentColor" />
            <p className="text-xs text-ayana-secondary leading-relaxed">Every check-in lets your parents know someone is thinking of them.</p>
          </div>

          <p className="mt-5 text-sm text-ayana-secondary text-center">
            Don't have an account?{" "}
            <Link to="/signup" className="text-ayana-gold font-semibold hover:underline" data-testid="login-to-signup">
              Set up Ayana for your parents
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}