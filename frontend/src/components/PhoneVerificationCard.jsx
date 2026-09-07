import { useState, useEffect } from "react";
import { ShieldCheck, Loader2, Send, RotateCw } from "lucide-react";
import { toast } from "sonner";
import { formatApiError } from "@/lib/api";

// Seconds the "Resend" button stays locked after a code is sent — keeps
// users from hammering it into the server's 3-sends-per-10-min rate limit.
const RESEND_COOLDOWN = 30;

// Reusable OTP verification card.
//
// Props:
//   label      - display name for this number, e.g. "Your number" / parent name
//   phone      - the phone number currently on the form/record
//   verified   - whether THIS phone is currently verified. Callers own this
//                logic: Dashboard passes user.phone_verified / p.phone_verified
//                directly; Onboarding should pass a *computed* value
//                (child.phone === verifiedPhone) so editing the phone after
//                verifying correctly drops the badge instead of showing a
//                stale "Verified" state on a number nobody confirmed.
//   onSend     - async (phone) => sends the OTP
//   onVerify   - async (phone, code) => verifies the OTP
//   onResend   - async (phone) => resends the OTP
//   onVerified - optional (phone) => called after a successful verify, so a
//                caller (Onboarding) can react — e.g. store verifiedPhone,
//                unlock "Continue", call refreshUser().
//   testid     - base data-testid, suffixed per interactive element
export function PhoneVerificationCard({
  label,
  phone,
  verified,
  onSend,
  onVerify,
  onResend,
  onVerified,
  testid,
}) {
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [resendBusy, setResendBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  // If the phone number changes (edited mid-onboarding) or the parent flips
  // `verified` back to false, don't leave a stale "enter code" box open on
  // the old number.
  useEffect(() => {
    setSent(false);
    setCode("");
    setCooldown(0);
  }, [phone, verified]);

  // Resend cooldown ticker.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((s) => (s <= 1 ? 0 : s - 1)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  // Auto-read the OTP on supported mobile browsers (WebOTP API — Chrome on
  // Android) so the user doesn't have to type it. Only active while the code
  // box is showing and the number isn't verified yet; silently no-ops
  // everywhere else (desktop, iOS, WhatsApp-delivered codes).
  useEffect(() => {
    if (!sent || verified) return;
    if (typeof window === "undefined" || !("OTPCredential" in window)) return;
    const ac = new AbortController();
    navigator.credentials
      .get({ otp: { transport: ["sms"] }, signal: ac.signal })
      .then((otp) => {
        if (otp?.code) setCode(otp.code.replace(/\D/g, "").slice(0, 6));
      })
      .catch(() => {});
    return () => ac.abort();
  }, [sent, verified]);

  const send = async () => {
    setBusy(true);
    try {
      const res = await onSend(phone);
      setSent(true);
      setCooldown(RESEND_COOLDOWN);
      const via = res?.channel === "whatsapp" ? "WhatsApp" : res?.channel === "sms" ? "SMS" : "WhatsApp/SMS";
      toast.success(`Code sent to ${phone} via ${via}`);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Could not send code.");
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    if (code.length < 4) return;
    setBusy(true);
    try {
      await onVerify(phone, code);
      toast.success(`${label} verified ✓`);
      setSent(false);
      setCode("");
      onVerified?.(phone);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Invalid or expired code.");
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    setResendBusy(true);
    try {
      await onResend(phone);
      setCooldown(RESEND_COOLDOWN);
      toast.success("New code sent.");
      setCode("");
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || "Could not resend code.");
    } finally {
      setResendBusy(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-ayana-line p-5" data-testid={testid}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-medium text-ayana-text">{label}</p>
          <p className="text-sm text-ayana-muted">{phone}</p>
        </div>
        {verified ? (
          <span
            className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-ayana-mint/20 text-[#0D9668]"
            data-testid={`${testid}-verified-badge`}
          >
            <ShieldCheck className="w-3.5 h-3.5" /> Verified
          </span>
        ) : !sent ? (
          <button
            onClick={send}
            disabled={busy || !phone}
            data-testid={`${testid}-send`}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-ayana-primary text-white text-xs font-medium hover:bg-ayana-primary-hover disabled:opacity-50"
          >
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />} Send code
          </button>
        ) : null}
      </div>

      {!verified && sent && (
        <div className="mt-4 flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
          <input
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder="6-digit code"
            inputMode="numeric"
            autoComplete="one-time-code"
            name="otp"
            maxLength={6}
            data-testid={`${testid}-code`}
            className="flex-1 px-3.5 py-2.5 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition"
          />
          <button
            onClick={verify}
            disabled={busy || code.length < 4}
            data-testid={`${testid}-verify`}
            className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50"
          >
            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Confirm
          </button>
          <button
            onClick={resend}
            disabled={resendBusy || cooldown > 0}
            data-testid={`${testid}-resend`}
            className="inline-flex items-center justify-center gap-1.5 px-3 py-2.5 text-xs text-ayana-secondary hover:text-ayana-primary transition-colors disabled:opacity-50 disabled:hover:text-ayana-secondary"
          >
            {resendBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RotateCw className="w-3.5 h-3.5" />}
            {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend"}
          </button>
        </div>
      )}
    </div>
  );
}