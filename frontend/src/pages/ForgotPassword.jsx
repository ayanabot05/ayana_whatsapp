import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { Logo } from "@/components/Logo";
import { PasswordStrength } from "@/components/PasswordStrength";
import { AuthBrandPanel } from "@/components/AuthBrandPanel";
import { api, formatAxiosError } from "@/lib/api";
import { passwordError } from "@/lib/validation";

const inputCls = "mt-1.5 w-full px-4 py-3 rounded-xl border border-ayana-line bg-white text-ayana-text focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition";

export default function ForgotPassword() {
  const navigate = useNavigate();
  const [step, setStep] = useState("email");
  const [email, setEmail] = useState("");
  const [challenge, setChallenge] = useState(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const sendCode = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { data } = await api.post("/auth/forgot-password", { email });
      setChallenge(data.challenge_id);
      toast.success(data.message || "Code sent.");
      setStep("reset");
    } catch (err) {
      setError(formatAxiosError(err));
    } finally { setLoading(false); }
  };

  const reset = async (e) => {
    e.preventDefault();
    setError("");
    const msg = passwordError(password);
    if (msg) { setError(msg); return; }
    if (password !== confirm) { setError("Passwords don't match."); return; }
    setLoading(true);
    try {
      await api.post("/auth/reset-password", { email, challenge_id: challenge, code: code.trim(), new_password: password });
      toast.success("Password updated. Log in with your new password.");
      navigate("/login");
    } catch (err) {
      setError(formatAxiosError(err));
    } finally { setLoading(false); }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-ayana-bg">
      <AuthBrandPanel />
      <div className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md" data-testid="forgot-page">
          <Link to="/" className="lg:hidden flex items-center justify-center mb-8"><Logo size={36} /></Link>
          <Link to="/login" className="inline-flex items-center gap-1 text-sm text-ayana-secondary hover:text-ayana-text" data-testid="forgot-back"><ArrowLeft className="w-4 h-4" /> Back to log in</Link>
          <h1 className="mt-4 font-display text-3xl font-semibold text-ayana-text">Reset your password</h1>
          <p className="mt-2 text-ayana-secondary">
            {step === "email" ? "Enter your account email. We'll email a 6-digit verification code." : "Enter your email code and choose a new password."}
          </p>

          {step === "email" ? (
            <form onSubmit={sendCode} className="mt-8 space-y-4" data-testid="forgot-form">
              <div>
                <label className="text-sm font-medium text-ayana-text" htmlFor="forgot-email">Email</label>
                <input id="forgot-email" type="email" required value={email} onChange={e => setEmail(e.target.value)} data-testid="forgot-email" className={inputCls} autoComplete="email" />
              </div>
              {error && <p className="text-sm text-red-600" data-testid="forgot-error">{error}</p>}
              <button type="submit" disabled={loading} data-testid="forgot-send" className="w-full btn-saffron flex items-center justify-center gap-2 px-6 py-3.5 rounded-full font-semibold disabled:opacity-60">
                {loading && <Loader2 className="w-4 h-4 animate-spin" />} Send code
              </button>
            </form>
          ) : (
            <form onSubmit={reset} className="mt-8 space-y-4" data-testid="reset-form">
              <div>
                <label className="text-sm font-medium text-ayana-text">6-digit code</label>
                <input inputMode="numeric" maxLength={6} required value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} data-testid="reset-code" placeholder="123456" className={`${inputCls} tracking-[0.3em] text-center font-semibold`} />
              </div>
              <div>
                <label className="text-sm font-medium text-ayana-text">New password</label>
                <input type="password" value={password} onChange={e => setPassword(e.target.value)} data-testid="reset-password" className={inputCls} required minLength={8} maxLength={128} autoComplete="new-password" />
                 <PasswordStrength password={password} testid="reset-password-strength" />
              </div>
              <div>
                <label className="text-sm font-medium text-ayana-text">Confirm new password</label>
                <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} data-testid="reset-password-confirm" className={inputCls} required maxLength={128} autoComplete="new-password" />
                 </div>
              {error && <p className="text-sm text-red-600" data-testid="reset-error">{error}</p>}
              <button type="submit" disabled={loading} data-testid="reset-submit" className="w-full btn-saffron flex items-center justify-center gap-2 px-6 py-3.5 rounded-full font-semibold disabled:opacity-60">
                {loading && <Loader2 className="w-4 h-4 animate-spin" />} Set new password
              </button>
              <button type="button" onClick={() => { setStep("email"); setError(""); setCode(''); }} className="w-full text-sm text-ayana-secondary hover:text-ayana-text" data-testid="reset-resend">Didn't get it? Send again</button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
