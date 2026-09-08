
import { useState } from "react";
import { Loader2, Check, Mail, Lock } from "lucide-react";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";

const inputCls = "w-full px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition";

export function ChangeEmailCard({ user, refreshUser }) {
  const [email, setEmail] = useState(user?.email || "");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!email.trim() || !email.includes("@")) {
      toast.error("Please enter a valid email address.");
      return;
    }
    if (email.trim() === user?.email) {
      toast("Email is already " + user?.email);
      return;
    }
    setBusy(true);
    try {
      await api.put("/auth/email", { email: email.trim() });
      toast.success("Email updated successfully.");
      refreshUser?.();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-ayana-line p-6">
      <h3 className="font-display text-base font-medium text-ayana-text flex items-center gap-2"><Mail className="w-4 h-4" /> Change email</h3>
      <p className="text-xs text-ayana-muted mt-1">Your login email. We'll send important updates here.</p>
      <div className="mt-4 flex gap-2">
        <input value={email} onChange={(e) => setEmail(e.target.value)} className={inputCls} placeholder="new@email.com" data-testid="change-email-input" />
        <button onClick={save} disabled={busy} data-testid="change-email-save" className="px-5 py-2.5 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : "Save"}
        </button>
      </div>
    </div>
  );
}

export function ChangePasswordCard({ refreshUser }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!current || !next) {
      toast.error("Please fill current and new password.");
      return;
    }
    if (next.length < 8) {
      toast.error("New password must be at least 8 characters.");
      return;
    }
    if (next !== confirm) {
      toast.error("New passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.put("/auth/password", {
        current_password: current,
        new_password: next,
      });
      // IMPORTANT: Do NOT logout. User stays logged in.
      // Clear fields and show clear message.
      setCurrent("");
      setNext("");
      setConfirm("");
      toast.success("Password changed successfully. You remain logged in on this device.", { duration: 5000 });
      // Refresh user context so any UI that depends on auth stays fresh
      refreshUser?.();
    } catch (e) {
      const msg = formatApiError(e.response?.data?.detail);
      if (msg.toLowerCase().includes("current") || msg.toLowerCase().includes("incorrect")) {
        toast.error("Current password is incorrect. Please try again.");
      } else {
        toast.error(msg);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-ayana-line p-6">
      <h3 className="font-display text-base font-medium text-ayana-text flex items-center gap-2"><Lock className="w-4 h-4" /> Change password</h3>
      <p className="text-xs text-ayana-muted mt-1">After changing, you stay logged in here. Other devices will need to log in again.</p>
      <div className="mt-4 space-y-3">
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="Current password" className={inputCls} data-testid="current-password" />
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)} placeholder="New password (min 8 chars)" className={inputCls} data-testid="new-password" />
        <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Confirm new password" className={inputCls} data-testid="confirm-password" />
        <button onClick={save} disabled={busy} data-testid="change-password-save" className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} Update password
        </button>
      </div>
    </div>
  );
}

