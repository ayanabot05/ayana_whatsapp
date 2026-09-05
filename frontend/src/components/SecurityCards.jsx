/**
 * SecurityCards.jsx — Account tab security widgets:
 *  • ChangeEmailCard — email-based OTP flow (profile/email/request + confirm)
 *  • ChangePasswordCard — current/new password with strength meter
 */
import { useState } from "react";
import { Mail, KeyRound, Loader2 } from "lucide-react";
import { api, formatAxiosError } from "@/lib/api";
import { toast } from "sonner";

const inputCls = "w-full px-3.5 py-2.5 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-accent/50 focus:border-ayana-accent transition";
const btnCls = "inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50";

function passwordError(pw) {
  if (!pw || pw.length < 8) return "Password must be at least 8 characters.";
  if (!/[A-Z]/.test(pw)) return "Password must contain at least one uppercase letter.";
  if (!/[0-9]/.test(pw)) return "Password must contain at least one number.";
  return null;
}

function PasswordStrength({ password, testid }) {
  if (!password) return null;
  const checks = [
    { label: "8+ characters", ok: password.length >= 8 },
    { label: "1 uppercase letter", ok: /[A-Z]/.test(password) },
    { label: "1 number", ok: /[0-9]/.test(password) },
  ];
  return (
    <div className="mt-1.5 flex flex-wrap gap-2" data-testid={testid}>
      {checks.map((c) => (
        <span
          key={c.label}
          className={`text-xs px-2 py-0.5 rounded-full ${c.ok ? "bg-green-100 text-green-700" : "bg-ayana-alt text-ayana-muted"}`}
        >
          {c.ok ? "✓" : "○"} {c.label}
        </span>
      ))}
    </div>
  );
}

export function ChangeEmailCard({ user, refreshUser }) {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);

  const request = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { data } = await api.post("/profile/email/request", { new_email: email.trim(), password });
      setPending(data);
      toast.success(`Code sent to ${email.trim()}`);
    } catch (err) { toast.error(formatAxiosError(err)); } finally { setBusy(false); }
  };

  const confirm = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/profile/email/confirm", { code: code.trim() });
      toast.success("Email updated.");
      setOpen(false); setPending(null); setEmail(""); setPassword(""); setCode("");
      if (refreshUser) await refreshUser();
    } catch (err) { toast.error(formatAxiosError(err)); } finally { setBusy(false); }
  };

  return (
    <div className="bg-white rounded-xl border border-ayana-line p-6" data-testid="change-email-card">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg font-medium text-ayana-text flex items-center gap-2"><Mail className="w-4 h-4 text-ayana-primary" /> Login email</h3>
        {!open && <button onClick={() => setOpen(true)} data-testid="change-email-open" className="text-sm text-ayana-primary font-medium hover:underline">Change</button>}
      </div>
      <p className="mt-1 text-sm text-ayana-secondary">{user?.email}</p>
      {open && !pending && (
        <form onSubmit={request} className="mt-4 space-y-3" data-testid="change-email-form">
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="new@email.com" data-testid="change-email-new" className={inputCls} />
          <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Current password" data-testid="change-email-password" className={inputCls} />
          <p className="text-xs text-ayana-muted">We'll email a code to your new address to confirm. Your old email becomes free for a new account.</p>
          <div className="flex gap-2">
            <button type="submit" disabled={busy} data-testid="change-email-submit" className={btnCls}>{busy && <Loader2 className="w-4 h-4 animate-spin" />} Send code</button>
            <button type="button" onClick={() => setOpen(false)} className="text-sm text-ayana-secondary px-3">Cancel</button>
          </div>
        </form>
      )}
      {open && pending && (
        <form onSubmit={confirm} className="mt-4 space-y-3" data-testid="change-email-confirm-form">
          <p className="text-sm text-ayana-secondary">Changing to <b className="text-ayana-text">{pending.pending_email}</b>. Enter the code we emailed there.</p>
          {pending.dev_code && <p className="text-xs rounded-lg bg-amber-50 border border-amber-200 text-amber-800 px-3 py-2" data-testid="change-email-dev-code">Email test mode — code: <b>{pending.dev_code}</b></p>}
          <input inputMode="numeric" maxLength={6} required value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} placeholder="6-digit code" data-testid="change-email-code" className={inputCls} />
          <div className="flex gap-2">
            <button type="submit" disabled={busy} data-testid="change-email-confirm" className={btnCls}>{busy && <Loader2 className="w-4 h-4 animate-spin" />} Confirm</button>
            <button type="button" onClick={() => setPending(null)} className="text-sm text-ayana-secondary px-3">Back</button>
          </div>
        </form>
      )}
    </div>
  );
}

export function ChangePasswordCard() {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const msg = passwordError(next);
    if (msg) { toast.error(msg); return; }
    if (next !== confirm) { toast.error("Passwords don't match."); return; }
    setBusy(true);
    try {
      await api.post("/auth/change-password", { current_password: current, new_password: next });
      toast.success("Password changed.");
      setOpen(false); setCurrent(""); setNext(""); setConfirm("");
    } catch (err) { toast.error(formatAxiosError(err)); } finally { setBusy(false); }
  };

  return (
    <div className="bg-white rounded-xl border border-ayana-line p-6" data-testid="change-password-card">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg font-medium text-ayana-text flex items-center gap-2"><KeyRound className="w-4 h-4 text-ayana-primary" /> Password</h3>
        {!open && <button onClick={() => setOpen(true)} data-testid="change-password-open" className="text-sm text-ayana-primary font-medium hover:underline">Change</button>}
      </div>
      {!open && <p className="mt-1 text-sm text-ayana-secondary">••••••••</p>}
      {open && (
        <form onSubmit={submit} className="mt-4 space-y-3" data-testid="change-password-form">
          <input type="password" required value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="Current password" data-testid="change-password-current" className={inputCls} />
          <div>
            <input type="password" required value={next} onChange={(e) => setNext(e.target.value)} placeholder="New password (8+ chars, 1 uppercase, 1 number)" data-testid="change-password-new" className={inputCls} />
            <PasswordStrength password={next} testid="change-password-strength" />
          </div>
          <input type="password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Confirm new password" data-testid="change-password-confirm" className={inputCls} />
          <div className="flex gap-2">
            <button type="submit" disabled={busy} data-testid="change-password-submit" className={btnCls}>{busy && <Loader2 className="w-4 h-4 animate-spin" />} Update password</button>
            <button type="button" onClick={() => setOpen(false)} className="text-sm text-ayana-secondary px-3">Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}