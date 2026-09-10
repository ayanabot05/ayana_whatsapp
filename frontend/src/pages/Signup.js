import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Loader2, Heart } from "lucide-react";
import { Logo } from "@/components/Logo";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PhoneInput } from "@/components/PhoneInput";
import { PasswordStrength } from "@/components/PasswordStrength";
import { phoneError, passwordError } from "@/lib/validation";
import { toast } from "sonner";
import { AuthBrandPanel } from "@/components/AuthBrandPanel";

export default function Signup() {
  const { loginWithToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const inviteEmail = searchParams.get("email") || searchParams.get("invite") || "";
  const inviteToken = searchParams.get("invite_token") || "";

  const [form, setForm] = useState({
    name: "",
    email: inviteEmail,
    phone: "+91",
    password: ""
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const [submitError, setSubmitError] = useState(null);
  const [loading, setLoading] = useState(false);

  const upd = (k) => (e) => {
    setForm({...form, [k]: e.target.value });
    if (fieldErrors[k]) setFieldErrors(prev => ({...prev, [k]: "" }));
    if (submitError) setSubmitError(null);
  };

  const handlePhoneChange = (v) => {
    setForm({...form, phone: v });
    if (fieldErrors.phone) setFieldErrors(prev => ({...prev, phone: "" }));
    if (submitError) setSubmitError(null);
  };

  const validateForm = () => {
    const errs = {};
    if (!form.name.trim()) errs.name = "Your name is required.";

    if (!form.email.trim()) {
      errs.email = "Email is required.";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      errs.email = "Enter a valid email address.";
    }

    const pErr = phoneError(form.phone);
    if (pErr) errs.phone = pErr;

    const pwErr = passwordError(form.password);
    if (pwErr) errs.password = pwErr;

    return errs;
  };

  const getFriendlyApiError = (err) => {
    const status = err.response?.status;
    const detail = err.response?.data?.detail || "";
    const detailStr = typeof detail === "string"? detail : JSON.stringify(detail);
    const low = detailStr.toLowerCase();

    // Email already exists
    if (status === 409 || low.includes("already exists") && low.includes("email")) {
      return {
        message: `An account with ${form.email} already exists.`,
        action: { label: "Log in instead", to: `/login?email=${encodeURIComponent(form.email)}` },
        field: "email"
      };
    }
    // Phone already used as parent
    if (low.includes("already set up as a parent") || low.includes("different phone number")) {
      return {
        message: detailStr,
        field: "phone"
      };
    }
    // Phone validation from backend
    if (low.includes("needs") && low.includes("digits") || low.includes("phone number must")) {
      return {
        message: detailStr,
        field: "phone"
      };
    }
    return { message: detailStr || err.message || "Something went wrong. Please try again." };
  };

  const submit = async (e) => {
    e.preventDefault();
    setSubmitError(null);

    const errs = validateForm();
    if (Object.keys(errs).length > 0) {
      setFieldErrors(errs);
      const firstErr = Object.values(errs)[0];
      setSubmitError({ message: firstErr });
      return;
    }

    setLoading(true);
    try {
      const payload = {
       ...form,
        name: form.name.trim(),
        email: form.email.trim().toLowerCase(),
      };
      const { data } = await api.post("/auth/register", payload);
      loginWithToken(data.access_token, data.refresh_token, data.user);

      if (data.user.household_owner_id) {
        toast.success("You've joined the family care circle 💛");
        navigate("/dashboard");
      } else if (inviteToken) {
        navigate(`/invite/${inviteToken}`);
      } else {
        toast.success("Welcome! Let's bring Ayana into your parents' day. 💛");
        navigate("/onboarding");
      }
    } catch (err) {
      const friendly = getFriendlyApiError(err);
      if (friendly.field) {
        setFieldErrors(prev => ({...prev, [friendly.field]: friendly.message }));
      }
      setSubmitError(friendly);
    } finally {
      setLoading(false);
    }
  };

  const inputBaseClass = "mt-1.5 w-full px-4 py-3 rounded-xl border bg-white focus:outline-none focus:ring-2 transition";
  const inputOk = "border-ayana-line focus:ring-ayana-gold/40 focus:border-ayana-gold";
  const inputErr = "border-red-400 focus:ring-red-200 focus:border-red-400";

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-warm-cream">
      <AuthBrandPanel
        headline="A few minutes now. Warmth for them, every day after."
        bullets={["Set up in under 5 minutes", "No app for your parents — just WhatsApp", "Their language, their time, their comfort"]}
        emotionalQuote="You may live in another country, but your parents should never have to spend the day waiting to hear from you."
        footer="Ayana supports your care — it never replaces it."
        showPhone
      />

      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <Link to="/" className="lg:hidden flex items-center justify-center mb-8">
            <Logo size={36} />
          </Link>
          <h1 className="font-display text-3xl font-semibold text-ayana-text">Set up Ayana for your parents</h1>
          <p className="mt-2 text-ayana-secondary text-[15px]">Takes a few minutes. Your parents only need WhatsApp.</p>

          <form onSubmit={submit} className="mt-8 space-y-4" data-testid="signup-form" noValidate>
            <div>
              <label className="text-sm font-medium text-ayana-text">Your name</label>
              <input
                required
                value={form.name}
                onChange={upd("name")}
                data-testid="signup-name"
                placeholder="Your full name"
                className={`${inputBaseClass} ${fieldErrors.name ? inputErr : inputOk}`}
              />
              {fieldErrors.name && <p className="mt-1 text-xs text-red-600">{fieldErrors.name}</p>}
            </div>

            <div>
              <label className="text-sm font-medium text-ayana-text">Email</label>
              <input
                type="email"
                required
                value={form.email}
                onChange={upd("email")}
                data-testid="signup-email"
                placeholder="you@example.com"
                className={`${inputBaseClass} ${fieldErrors.email ? inputErr : inputOk}`}
              />
              {fieldErrors.email && <p className="mt-1 text-xs text-red-600">{fieldErrors.email}</p>}
            </div>

            <div>
              <label className="text-sm font-medium text-ayana-text">Phone</label>
              <div className="mt-1.5">
                <PhoneInput value={form.phone} onChange={handlePhoneChange} testid="signup-phone" />
              </div>
              {(fieldErrors.phone || (form.phone.length > 4 && phoneError(form.phone))) && (
                <p className="mt-1 text-xs text-red-600" data-testid="signup-phone-error">
                  {fieldErrors.phone || phoneError(form.phone)}
                </p>
              )}
            </div>

            <div>
              <label className="text-sm font-medium text-ayana-text">Password</label>
              <input
                type="password"
                required
                value={form.password}
                onChange={upd("password")}
                data-testid="signup-password"
                placeholder="8+ chars, 1 uppercase, 1 number"
                className={`${inputBaseClass} ${fieldErrors.password ? inputErr : inputOk}`}
              />
              <PasswordStrength password={form.password} testid="signup-password-strength" />
              {fieldErrors.password && <p className="mt-1 text-xs text-red-600">{fieldErrors.password}</p>}
            </div>

            {submitError && (
              <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3" data-testid="signup-error">
                <p className="text-sm text-red-700">
                  {submitError.message}
                  {submitError.action && (
                    <>
                      {" "}
                      <Link to={submitError.action.to} className="font-semibold underline hover:text-red-800">
                        {submitError.action.label}
                      </Link>
                    </>
                  )}
                </p>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              data-testid="signup-submit"
              className="w-full btn-saffron flex items-center justify-center gap-2 px-6 py-3.5 rounded-full font-semibold disabled:opacity-60"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />} Start caring between calls
            </button>

            <p className="text-xs text-ayana-muted text-center">
              By continuing you agree to our{" "}
              <Link to="/terms" className="underline text-ayana-gold">Terms</Link> &{" "}
              <Link to="/privacy" className="underline text-ayana-gold">Privacy Policy</Link>.
            </p>
          </form>

          {/* Emotional nudge */}
          <div className="mt-6 flex items-center gap-2.5 bg-amber-50/80 border border-amber-200/50 rounded-xl px-4 py-3">
            <Heart className="w-4 h-4 text-ayana-gold shrink-0" fill="currentColor" />
            <p className="text-xs text-ayana-secondary leading-relaxed">Your parents don't need to learn anything new. Ayana reaches them on WhatsApp, in their language.</p>
          </div>

          <p className="mt-5 text-sm text-ayana-secondary text-center">
            Already have an account?{" "}
            <Link to="/login" className="text-ayana-gold font-semibold hover:underline" data-testid="signup-to-login">
              Log in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}