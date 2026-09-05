import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { Logo } from "@/components/Logo";
import { PhoneInput } from "@/components/PhoneInput";
import { PasswordStrength } from "@/components/PasswordStrength";
import { AuthBrandPanel } from "@/components/AuthBrandPanel";
import { api, formatAxiosError } from "@/lib/api";
import { phoneError, passwordError } from "@/lib/validation";

const inputCls = "mt-1.5 w-full px-4 py-3 rounded-xl border border-ayana-line bg-white text-ayana-text focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition";

export default function ForgotPassword() {
  const navigate = useNavigate();
  const [step, setStep] = useState("phone");
  const [phone, setPhone] = useState("+91");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [devCode, setDevCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const sendCode = async (e) => {
    e.preventDefault();
    setError("");
    const msg = phoneError(phone);
    if (msg) { setError(msg); return; }
    setLoading(true);
    try {
      const { data } = await api.post("/auth/forgot-password", { phone });
      if (data.dev_code) setDevCode(data.dev_code);
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
      await api.post("/auth/reset-password", { phone, code: code.trim(), new_password: password });
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
            {step === "phone" ? "Enter the phone number on your account. We'll SMS you a 6-digit code." : "Enter the code we sent and choose a new password."}
          </p>

          {step === "phone" ? (
            <form onSubmit={sendCode} className="mt-8 space-y-4" data-testid="forgot-form">
              <div>
                <label className="text-sm font-medium text-ayana-text">Phone</label>
                <div className="mt-1.5"><PhoneInput value={phone} onChange={setPhone} testid="forgot-phone" /></div>
              </div>
              {error && <p className="text-sm text-red-600" data-testid="forgot-error">{error}</p>}
              <button type="submit" disabled={loading} data-testid="forgot-send" className="w-full btn-saffron flex items-center justify-center gap-2 px-6 py-3.5 rounded-full font-semibold disabled:opacity-60">
                {loading && <Loader2 className="w-4 h-4 animate-spin" />} Send code
              </button>
            </form>
          ) : (
            <form onSubmit={reset} className="mt-8 space-y-4" data-testid="reset-form">
              {devCode && <p className="text-xs rounded-lg bg-amber-50 border border-amber-200 text-amber-800 px-3 py-2" data-testid="forgot-dev-code">SMS is in test mode — your code is <b>{devCode}</b></p>}
              <div>
                <label className="text-sm font-medium text-ayana-text">6-digit code</label>
                <input inputMode="numeric" maxLength={6} required value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} data-testid="reset-code" placeholder="123456" className={`${inputCls} tracking-[0.3em] text-center font-semibold`} />
              </div>
              <div>
                <label className="text-sm font-medium text-ayana-text">New password</label>
                <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} data-testid="reset-password" placeholder="8+ chars, 1 uppercase, 1 number" className={inputCls} />
                <PasswordStrength password={password} testid="reset-password-strength" />
              </div>
              <div>
                <label className="text-sm font-medium text-ayana-text">Confirm new password</label>
                <input type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} data-testid="reset-confirm" className={inputCls} />
              </div>
              {error && <p className="text-sm text-red-600" data-testid="reset-error">{error}</p>}
              <button type="submit" disabled={loading} data-testid="reset-submit" className="w-full btn-saffron flex items-center justify-center gap-2 px-6 py-3.5 rounded-full font-semibold disabled:opacity-60">
                {loading && <Loader2 className="w-4 h-4 animate-spin" />} Set new password
              </button>
              <button type="button" onClick={() => { setStep("phone"); setError(""); }} className="w-full text-sm text-ayana-secondary hover:text-ayana-text" data-testid="reset-resend">Didn't get it? Send again</button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
