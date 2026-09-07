import { useState, useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Logo } from "@/components/Logo";
import { api, formatApiError } from "@/lib/api";
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
  const [form, setForm] = useState({ name: "", email: inviteEmail, phone: "+91", password: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [geo, setGeo] = useState({
    city: "",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, // dynamic - Asia/Kolkata for you
    country_code: "IN",
  });

  // Dynamic location -> no hardcoded default
  useEffect(() => {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    setGeo(g => ({...g, timezone: tz }));

    // Get city + more accurate timezone from IP
    fetch("https://ipapi.co/json/")
     .then(r => r.json())
     .then(d => {
        setGeo(g => ({
          city: d.city || g.city,
          timezone: d.timezone || g.timezone,
          country_code: d.country_code || g.country_code,
        }));
      })
     .catch(() => {});
  }, []);

  const upd = (k) => (e) => setForm({...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    const phoneMsg = phoneError(form.phone);
    if (phoneMsg) { setError(phoneMsg); return; }
    const pwMsg = passwordError(form.password);
    if (pwMsg) { setError(pwMsg); return; }
    setLoading(true);
    try {
      // merge dynamic geo into payload
      const payload = {
       ...form,
        city: geo.city || null,
        timezone: geo.timezone, // never null now
        country_code: geo.country_code,
      };
      const { data } = await api.post("/auth/register", payload);
      loginWithToken(data.access_token, data.refresh_token, data.user);
      if (data.user.household_owner_id) {
        toast.success("You've joined the family care circle 💛");
        navigate("/dashboard");
      } else if (inviteToken) {
        navigate(`/invite/${inviteToken}`);
      } else {
        toast.success("Account created. Let's set up their care circle.");
        navigate("/onboarding");
      }
    } catch (err) {
      setError(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid lg:grid-cols-2 bg-warm-cream">
      <AuthBrandPanel
        headline="A few minutes now. Warmth for them, every day after."
        bullets={["Set up in minutes", "No app for your parents", "Their language, their time"]}
        footer="AYANA supports your care — it never replaces it."
        showPhone
      />
      <div className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <Link to="/" className="lg:hidden flex items-center justify-center mb-8"><Logo size={36} /></Link>
          <h1 className="font-display text-3xl font-semibold text-ayana-text">Create your account</h1>
          <p className="mt-2 text-ayana-secondary">Begin their care circle today.</p>
          <form onSubmit={submit} className="mt-8 space-y-4" data-testid="signup-form">
            <div>
              <label className="text-sm font-medium text-ayana-text">Your name</label>
              <input required value={form.name} onChange={upd("name")} data-testid="signup-name" placeholder="Your full name"
                className="mt-1.5 w-full px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition" />
            </div>
            <div>
              <label className="text-sm font-medium text-ayana-text">Email</label>
              <input type="email" required value={form.email} onChange={upd("email")} data-testid="signup-email" placeholder="you@example.com"
                className="mt-1.5 w-full px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition" />
            </div>
            <div>
              <label className="text-sm font-medium text-ayana-text">Phone</label>
              <div className="mt-1.5"><PhoneInput value={form.phone} onChange={(v) => setForm({...form, phone: v })} testid="signup-phone" /></div>
              {form.phone.length > 4 && phoneError(form.phone) && <p className="mt-1 text-xs text-red-600" data-testid="signup-phone-error">{phoneError(form.phone)}</p>}
            </div>
            <div>
              <label className="text-sm font-medium text-ayana-text">Password</label>
              <input type="password" required minLength={8} value={form.password} onChange={upd("password")} data-testid="signup-password" placeholder="8+ chars, 1 uppercase, 1 number"
                className="mt-1.5 w-full px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition" />
              <PasswordStrength password={form.password} testid="signup-password-strength" />
            </div>
            {error && <p className="text-sm text-red-600" data-testid="signup-error">{error}</p>}
            <button type="submit" disabled={loading} data-testid="signup-submit"
              className="w-full btn-saffron flex items-center justify-center gap-2 px-6 py-3.5 rounded-full font-semibold disabled:opacity-60">
              {loading && <Loader2 className="w-4 h-4 animate-spin" />} Create account
            </button>
            <p className="text-xs text-ayana-muted text-center">By continuing you agree to our{" "}
              <Link to="/terms" className="underline text-ayana-bright">Terms</Link> &{" "}
              <Link to="/privacy" className="underline text-ayana-bright">Privacy Policy</Link>.</p>
          </form>
          <p className="mt-6 text-sm text-ayana-secondary text-center">
            Already have an account?{" "}
            <Link to="/login" className="text-ayana-bright font-semibold hover:underline" data-testid="signup-to-login">Log in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}