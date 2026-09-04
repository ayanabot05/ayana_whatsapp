import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Loader2, ArrowRight, ArrowLeft, Check, MessageCircle, Sparkles, Plus, Trash2, Pencil,
} from "lucide-react";
import { api, formatApiError, formatAxiosError } from "../lib/api";
import { useAuth } from "@/context/AuthContext";
import { TIMEZONES } from "@/lib/constants";
import { PhoneInput } from "@/components/PhoneInput";
import { PhoneVerificationCard } from "@/components/PhoneVerificationCard";
import { PricingCards } from "@/components/PricingCards";
import { ParentCareForm, blankParentForm, blankMedicine } from "@/components/ParentCareForm";
import { toast } from "sonner";
import { Logo } from "@/components/Logo";
import { FALLBACK_PLANS, FALLBACK_CURRENCIES } from "../lib/fallbackPlans";
import { cleanHabits } from "../lib/formHelpers";

const STEPS = ["Welcome", "Your plan", "Your parents", "Activate"];

export default function Onboarding() {
  const { user, config, refreshUser } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(() => {
    const s = user?.onboarding_step?? 0;
    return Math.min(Math.max(s, 0), 3);
  });
  const [loading, setLoading] = useState(false);
  // Set true right before we intentionally route to /activation so the
  // onboarding_complete->/dashboard redirect effect doesn't hijack it.
  const skipRedirect = useRef(false);

  const [child, setChild] = useState({
    name: user?.name || "",
    phone: user?.phone || "+91",
    city: user?.city || "",
    timezone: user?.timezone || "Asia/Kolkata",
  });
  const [childConsent, setChildConsent] = useState(false);
  const [verifiedPhone, setVerifiedPhone] = useState(
    user?.phone_verified && user?.phone_verified_number ? user.phone_verified_number : ""
  );
  const [planId, setPlanId] = useState("nitya");

  const normPhone = (p) => (p || "").replace(/\s/g, "");
  const childPhoneVerified = !!verifiedPhone && normPhone(child.phone) === normPhone(verifiedPhone);

  const plans = useMemo(() => config?.plans?.length? config.plans : FALLBACK_PLANS, [config]);
  const currencies = config?.currencies?.length? config.currencies : FALLBACK_CURRENCIES;
  const plan = useMemo(() => plans.find((p) => p.id === planId), [plans, planId]);
  const limits = useMemo(() => plan?.limits || { checkins: 2, reminders: 2, parents: 1, templates_per_day: 4 }, [plan]);
  const parentLimit = limits.parents || 1;
  const maxCheckins = limits.checkins || 2;

  const defaultMessages = useCallback(() => [
    { time: "08:00", category: "morning_wish", type: "checkin" },
    { time: "13:00", category: "lunch", type: "checkin" },
    { time: "21:00", category: "goodnight", type: "checkin" },
  ].slice(0, maxCheckins), [maxCheckins]);

  const newBlankParent = useCallback(
    () => ({...blankParentForm(), messages: defaultMessages() }),
    [defaultMessages]
  );

  const [parentsList, setParentsList] = useState([]);
  const [parentsLoaded, setParentsLoaded] = useState(false);
  const [parentForm, setParentForm] = useState(null);
  const [editingParentId, setEditingParentId] = useState(null);
  const [parentConsent, setParentConsent] = useState(false);
  const [deletingId, setDeletingId] = useState(null);
  const [scheduleIds, setScheduleIds] = useState({});
  const [newMed, setNewMed] = useState(blankMedicine());

  useEffect(() => { if (!skipRedirect.current && (user?.onboarding_complete || user?.household_owner_id)) navigate("/dashboard"); }, [user?.onboarding_complete, user?.household_owner_id, navigate]);

  useEffect(() => {
    if (user &&!user.onboarding_complete) {
      const serverStep = Math.min(Math.max(user.onboarding_step?? 0, 0), 3);
      setStep(serverStep);
      setChild((prev) => ({
       ...prev,
        name: user.name || prev.name,
        phone: user.phone || prev.phone,
        city: user.city || prev.city,
        timezone: user.timezone || prev.timezone,
      }));
      if (user.phone_verified && user.phone_verified_number) setVerifiedPhone(user.phone_verified_number);
    }
  }, [user, user?.onboarding_complete, user?.onboarding_step, user?.name, user?.phone, user?.city, user?.timezone]);

  useEffect(() => {
    api.get("/payment/state").then(({ data }) => {
      const currentPlan = data?.state?.plan || "nitya";
      setPlanId(["nitya", "bandham", "raksha"].includes(currentPlan)? currentPlan : "nitya");
    }).catch(() => {});

    api.get("/parents").then(({ data }) => {
      setParentsList(data || []);
      setParentsLoaded(true);
    }).catch(() => setParentsLoaded(true));

    api.get("/schedules").then(({ data }) => {
      const map = {};
      for (const s of (data || [])) map[s.parent_id] = s.id;
      setScheduleIds(map);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (parentsLoaded && parentsList.length === 0 &&!parentForm) {
      setParentForm(newBlankParent());
      setEditingParentId(null);
    }
  }, [parentsLoaded, parentsList.length, parentForm, newBlankParent]);

  const inputCls = "w-full px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition";

  const saveChild = async () => {
    if (!childConsent) { toast.error("Please confirm consent to continue."); return; }
    if (!child.name.trim()) { toast.error("Please enter your name."); return; }
    if (child.phone.length < 8) { toast.error("Please enter a valid phone number."); return; }
    if (!childPhoneVerified) { toast.error("Please verify your phone number with the SMS code first."); return; }
    setLoading(true);
    try {
      await api.put("/profile/child", { name: child.name, phone: child.phone, city: child.city, timezone: child.timezone });
      await api.post("/consent", { consent_type: "child", agreed: true, text: "I consent to AYANA managing my care setup." });
      setStep(1);
    } catch (e) { toast.error(formatAxiosError(e)); } finally { setLoading(false); }
  };

  const sendChildOtp = async (phone) => {
    const { data } = await api.post("/auth/otp/send", { phone });
    if (data?.dev_code) toast.message(`Test mode code: ${data.dev_code}`, { duration: 8000 });
  };
  const verifyChildOtp = async (phone, code) => {
    await api.post("/auth/otp/verify", { phone, code });
    setVerifiedPhone(phone);
    refreshUser?.();
  };
  const resendChildOtp = async (phone) => {
    const { data } = await api.post("/auth/otp/resend", { phone });
    if (data?.dev_code) toast.message(`Test mode code: ${data.dev_code}`, { duration: 8000 });
  };

  const choosePlan = async (id, billing) => {
    setPlanId(id);
    setLoading(true);
    try {
      const { data } = await api.post("/payment/checkout", { plan: id, billing, origin_url: window.location.origin });
      if (data?.checkout_url) { window.location.href = data.checkout_url; return; }
      toast.success(`${plans.find(p => p.id === id)?.name} selected.`);
      setStep(2);
    } catch (e) { toast.error(formatAxiosError(e)); } finally { setLoading(false); }
  };

  const openAddParent = () => {
    if (parentsList.length >= parentLimit) {
      toast.error(`Your ${plan?.name || "plan"} allows up to ${parentLimit} parent(s). Upgrade your plan to add more.`);
      return;
    }
    setEditingParentId(null);
    setParentConsent(false);
    setNewMed(blankMedicine());
    setParentForm(newBlankParent());
  };

  const openEditParent = async (p) => {
    setLoading(true);
    try {
      let messages = defaultMessages();
      const schedRes = await api.get("/schedules");
      const mySched = (schedRes.data || []).find(s => s.parent_id === p.id);
      if (mySched) {
        messages = (mySched.messages || []).filter(m => m.type!== "reminder" && m.source!== "medicine_sync");
        if (messages.length === 0) messages = defaultMessages();
        setScheduleIds(prev => ({...prev, [p.id]: mySched.id }));
      }
      setEditingParentId(p.id);
      setParentConsent(true);
      setNewMed(blankMedicine());
      setParentForm({
        name: p.name || "",
        relationship: p.relationship || "mother",
        phone: p.phone || "+91",
        language: p.language || "en",
        timezone: p.timezone || "Asia/Kolkata",
        notes: p.notes || "",
        preferred_name: p.preferred_name || "",
        nicknames: p.nicknames || [],
        city: p.city || "",
        other_parent_name: p.other_parent_name || "",
        medicine_list: p.medicine_list || [],
        habits: p.habits || blankParentForm().habits,
        messages: messages,
      });
    } catch (e) {
      toast.error("Could not load parent details.");
    } finally {
      setLoading(false);
    }
  };

  const closeParentForm = () => {
    setParentForm(null);
    setEditingParentId(null);
    setParentConsent(false);
  };

  const saveParentForm = async () => {
    if (!parentForm.name.trim()) { toast.error("Please enter your parent's name."); return; }
    if (parentForm.phone.length < 8) { toast.error("Please enter a valid WhatsApp number."); return; }
    if (!parentConsent) { toast.error("Please confirm you have your parent's consent."); return; }
    if (parentForm.messages.length === 0) { toast.error("Add at least one daily check-in."); return; }
    if (parentForm.messages.length > maxCheckins) { toast.error(`Your plan allows up to ${maxCheckins} check-ins. Remove some or upgrade.`); return; }
    setLoading(true);
    try {
      const { messages, reengagement_hours, ...parentData } = parentForm;
      parentData.habits = cleanHabits(parentData.habits);
      let savedParent;
      if (editingParentId) {
        const { data } = await api.put(`/parents/${editingParentId}`, parentData);
        savedParent = data;
        setParentsList((list) => list.map((p) => (p.id === editingParentId? data : p)));
      } else {
        const { data } = await api.post("/parents", parentData);
        savedParent = data;
        setParentsList((list) => [...list, data]);
        await api.post("/consent", { consent_type: "parent", agreed: true, text: `Consent confirmed for parent ${parentForm.name}.` });
      }
      const existingSchedId = scheduleIds[savedParent.id];
      const schedPayload = { parent_id: savedParent.id, mode: planId, messages, active: true, reengagement_hours: reengagement_hours ?? 4 };
      let dropped = savedParent.medicine_reminders_dropped;
      if (existingSchedId) {
        const { data: schedData } = await api.put(`/schedules/${existingSchedId}`, schedPayload);
        dropped = dropped || schedData?.medicine_reminders_dropped;
      } else {
        const { data: schedData } = await api.post("/schedules", schedPayload);
        setScheduleIds(prev => ({...prev, [savedParent.id]: schedData.id }));
        dropped = dropped || schedData?.medicine_reminders_dropped;
      }
      toast.success(editingParentId? "Parent updated." : "Parent added!");
      if (dropped?.length) {
        toast.warning(`Your plan couldn't fit all medicine reminder times — dropped: ${dropped.join(", ")}. Upgrade for more, or adjust times.`, { duration: 8000 });
      }
      closeParentForm();
    } catch (e) {
      toast.error(formatAxiosError(e));
    } finally {
      setLoading(false);
    }
  };

  const deleteParent = async (p) => {
    setDeletingId(p.id);
    try {
      await api.delete(`/parents/${p.id}`);
      setParentsList((list) => list.filter((x) => x.id!== p.id));
      toast.success(`Removed ${p.name}.`);
    } catch (e) { toast.error(formatAxiosError(e)); } finally { setDeletingId(null); }
  };

  const activate = async () => {
    setLoading(true);
    try {
      // Activation fires a real Meta WhatsApp send per parent, which can
      // take 15-20s on the first cold call (measured 16.5s in production).
      // Override the default 30s axios timeout with a generous 60s so the
      // client waits for the actual result instead of falsely toasting a
      // failure while the server already sent the message.
      const { data } = await api.post("/activation/activate", null, { timeout: 60000 });
      if (data?.activated) {
        toast.success("🎉 Care Circle activated! Your parent will start receiving daily check-ins.");
        skipRedirect.current = true;
        navigate("/activation");
      } else {
        toast.warning("We couldn't reach WhatsApp just now — nothing was sent. You can retry activation from your dashboard.");
        navigate("/dashboard");
      }
      refreshUser();
    } catch (e) { toast.error(formatAxiosError(e)); } finally { setLoading(false); }
  };

  const parentNames = parentsList.map((p) => p.name).filter(Boolean).join(", ");

  return (
    <div className="min-h-screen bg-warm-cream relative">
      <div className="absolute inset-0 pointer-events-none" style={{ background: "radial-gradient(1200px 500px at 100% -5%, rgba(217,108,74,0.06), transparent), radial-gradient(900px 500px at -10% 10%, rgba(44,76,59,0.06), transparent)" }} aria-hidden="true" />
      <div className="border-b border-ayana-line bg-warm-cream/80 backdrop-blur-xl sticky top-0 z-40">
        <div className="max-w-3xl mx-auto px-5 sm:px-8 py-4">
          <div className="flex items-center gap-2 mb-3">
            <Logo size={32} showWord={false} />
            <span className="font-display font-semibold text-ayana-text">AYANA setup</span>
          </div>
          <div className="flex gap-1.5">
            {STEPS.map((s, i) => (
              <div key={s} className="flex-1">
                <div className={`h-1.5 rounded-full transition-colors duration-300 ${i <= step? "bg-ayana-bright" : "bg-ayana-line"}`} />
                <p className={`mt-1.5 text- ${i === step? "text-ayana-bright font-semibold" : "text-ayana-muted"} hidden sm:block`}>{s}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="relative max-w-3xl mx-auto px-5 sm:px-8 py-10 lg:py-14">
        <AnimatePresence mode="wait">
          <motion.div key={step} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.35 }}>
            {step === 0 && (
              <div>
                <div className="text-center mb-8">
                  <span className="inline-flex w-14 h-14 rounded-2xl items-center justify-center mb-4" style={{ background: "linear-gradient(135deg, rgba(255,107,53,0.15), rgba(255,201,60,0.15))" }}><Sparkles className="w-7 h-7 text-ayana-bright" strokeWidth={1.5} /></span>
                  <h1 className="font-display text-3xl font-semibold text-ayana-text">Let's bring you closer to home.</h1>
                  <p className="mt-3 text-ayana-secondary max-w-lg mx-auto">Take a breath. In a few gentle steps, your parent will start receiving warm daily care — in their language, on their time.</p>
                </div>
                <div className="bg-white rounded-2xl border border-ayana-line p-7 space-y-5">
                  <h3 className="font-display text-lg font-medium text-ayana-text">A little about you</h3>
                  <div>
                    <label className="text-sm font-medium text-ayana-text">Your name</label>
                    <input value={child.name} onChange={(e) => setChild({...child, name: e.target.value })} data-testid="child-name" className={`mt-1.5 ${inputCls}`} />
                  </div>
                  <div className="grid sm:grid-cols-2 gap-4">
                    <div>
                      <label className="text-sm font-medium text-ayana-text">Your phone</label>
                      <div className="mt-1.5"><PhoneInput value={child.phone} onChange={(v) => setChild({...child, phone: v })} testid="child-phone" /></div>
                    </div>
                    <div>
                      <label className="text-sm font-medium text-ayana-text">Your city (optional)</label>
                      <input value={child.city} onChange={(e) => setChild({...child, city: e.target.value })} data-testid="child-city" placeholder="London" className={`mt-1.5 ${inputCls}`} />
                    </div>
                  </div>
                  <div>
                    <label className="text-sm font-medium text-ayana-text">Your timezone</label>
                    <select value={child.timezone} onChange={(e) => setChild({...child, timezone: e.target.value })} data-testid="child-timezone" className={`mt-1.5 ${inputCls}`}>
                      {TIMEZONES.map((tz) => <option key={tz.value} value={tz.value}>{tz.label}</option>)}
                    </select>
                  </div>
                  <label className="flex items-start gap-3 pt-2 cursor-pointer">
                    <input type="checkbox" checked={childConsent} onChange={(e) => setChildConsent(e.target.checked)} data-testid="child-consent" className="mt-1 w-4 h-4 accent-ayana-primary" />
                    <span className="text-sm text-ayana-secondary">I consent to AYANA storing my details to manage care check-ins. I can delete my data anytime.</span>
                  </label>
                  <div className="pt-2">
                    <p className="text-sm font-medium text-ayana-text mb-2">Verify your phone number</p>
                    <PhoneVerificationCard
                      label="Your number"
                      phone={child.phone}
                      verified={childPhoneVerified}
                      onSend={sendChildOtp}
                      onVerify={verifyChildOtp}
                      onResend={resendChildOtp}
                      testid="child-otp"
                    />
                    {!childPhoneVerified && (
                      <p className="mt-2 text-xs text-ayana-muted">We'll text a 6-digit code to confirm this is your number. Verification is required to continue.</p>
                    )}
                  </div>
                </div>
                <div className="mt-6 flex justify-between">
                  <button onClick={() => navigate("/dashboard")} className="inline-flex items-center gap-2 px-6 py-3.5 rounded-full border border-ayana-line text-ayana-text hover:bg-ayana-alt transition-colors"><ArrowLeft className="w-4 h-4" /> Back</button>
                  <button onClick={saveChild} disabled={loading ||!child.name || child.phone.length < 8 ||!childPhoneVerified ||!childConsent} data-testid="step0-next"
                    className="inline-flex items-center gap-2 px-7 py-3.5 rounded-full bg-ayana-primary text-white font-medium hover:bg-ayana-primary-hover transition-colors disabled:opacity-50">
                    {loading? <Loader2 className="w-4 h-4 animate-spin" /> : <>Continue <ArrowRight className="w-4 h-4" /></>}
                  </button>
                </div>
              </div>
            )}
            {step === 1 && (
              <div>
                <div className="mb-8 text-center">
                  <h1 className="font-display text-3xl font-semibold text-ayana-text">Choose your care plan</h1>
                  <p className="mt-3 text-ayana-secondary max-w-lg mx-auto">Pick the pack that fits your family — this decides how many parents, check-ins, and medicine reminders you get.</p>
                </div>
                <PricingCards plans={plans} currencies={currencies} selectedPlan={planId} onSelect={choosePlan} />
                <div className="mt-6 flex justify-between">
                  <button onClick={() => setStep(0)} className="inline-flex items-center gap-2 px-6 py-3.5 rounded-full border border-ayana-line text-ayana-text hover:bg-ayana-alt transition-colors"><ArrowLeft className="w-4 h-4" /> Back</button>
                </div>
              </div>
            )}
            {step === 2 && (
              <div>
                <div className="mb-6">
                  <h1 className="font-display text-3xl font-semibold text-ayana-text">Who are we caring for?</h1>
                  <p className="mt-3 text-ayana-secondary">
                    Your <span className="font-medium text-ayana-text">{plan?.name || "plan"}</span> covers up to {parentLimit} parent{parentLimit === 1? "" : "s"}, {maxCheckins} daily check-ins, and {limits.reminders || 2} medicine reminders per parent.
                    {" "}{parentsList.length}/{parentLimit} added.
                  </p>
                </div>
                {parentsList.length > 0 && (
                  <div className="mb-5 space-y-3">
                    {parentsList.map((p) => (
                      <div key={p.id} className="bg-white rounded-2xl border border-ayana-line p-5 flex items-center justify-between">
                        <div>
                          <p className="font-medium text-ayana-text">{p.name} <span className="text-ayana-muted font-normal capitalize">· {p.relationship}</span></p>
                          <p className="text-sm text-ayana-secondary">{p.phone}</p>
                          {(p.medicine_list || []).length > 0 && (
                            <p className="text-xs text-ayana-muted mt-1">💊 {p.medicine_list.length} medicine{p.medicine_list.length!== 1? "s" : ""}</p>
                          )}
                        </div>
                        <div className="flex items-center gap-1">
                          <button onClick={() => openEditParent(p)} className="p-2.5 rounded-full text-ayana-secondary hover:bg-ayana-alt hover:text-ayana-text transition-colors"><Pencil className="w-4 h-4" /></button>
                          <button onClick={() => deleteParent(p)} disabled={deletingId === p.id} className="p-2.5 rounded-full text-ayana-secondary hover:bg-red-50 hover:text-red-500 transition-colors disabled:opacity-50">
                            {deletingId === p.id? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {!parentForm && parentsList.length < parentLimit && (
                  <button onClick={openAddParent} data-testid="add-parent" className="mb-5 inline-flex items-center gap-2 px-5 py-3 rounded-full border border-dashed border-ayana-line text-ayana-text hover:bg-ayana-alt transition-colors">
                    <Plus className="w-4 h-4" /> Add {parentsList.length === 0? "a parent" : "another parent"}
                  </button>
                )}
                {parentForm && (
                  <div className="bg-white rounded-2xl border border-ayana-line overflow-hidden shadow-sm" data-testid="parent-form">
                    <div className="bg-ayana-alt/50 border-b border-ayana-line px-7 py-4 flex items-center justify-between">
                      <h3 className="font-display font-medium text-ayana-text">{editingParentId? "Edit parent" : "Add a parent"}</h3>
                      <button onClick={closeParentForm} className="text-sm text-ayana-muted hover:text-ayana-text">Cancel</button>
                    </div>
                    <div className="p-7 space-y-10">
                      <ParentCareForm form={parentForm} setForm={setParentForm} newMed={newMed} setNewMed={setNewMed} config={config} limits={limits} plan={plan} idPrefix="parent" />
                      <div className="pt-4 border-t border-ayana-line">
                        <label className="flex items-start gap-3 cursor-pointer">
                          <input type="checkbox" checked={parentConsent} onChange={(e) => setParentConsent(e.target.checked)} data-testid="parent-consent" className="mt-1 w-4 h-4 accent-ayana-primary" />
                          <span className="text-sm text-ayana-secondary">I confirm my parent is aware of and consents to receiving these caring messages on WhatsApp.</span>
                        </label>
                      </div>
                      <div className="flex flex-col items-end gap-2 pt-2">
                        <button onClick={saveParentForm} disabled={loading ||!parentForm.name || parentForm.phone.length < 8 ||!parentConsent} data-testid="save-parent"
                          className="inline-flex items-center gap-2 px-8 py-4 rounded-full bg-ayana-primary text-white font-semibold hover:bg-ayana-primary-hover transition-colors shadow-md disabled:opacity-50">
                          {loading? <Loader2 className="w-4 h-4 animate-spin" /> : <>{editingParentId? "Save changes" : "Confirm parent"} <Check className="w-4 h-4" /></>}
                        </button>
                        {loading && (
                          <p className="text-xs text-ayana-secondary italic" data-testid="save-parent-pending-copy">
                            Setting up their care schedule — this can take up to 30 seconds…
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                )}
                <div className="mt-8 flex justify-between">
                  <button onClick={() => setStep(1)} className="inline-flex items-center gap-2 px-6 py-3.5 rounded-full border border-ayana-line text-ayana-text hover:bg-ayana-alt transition-colors"><ArrowLeft className="w-4 h-4" /> Back</button>
                  <button onClick={() => setStep(3)} disabled={loading || parentsList.length === 0 || parentForm} data-testid="step2-next"
                    className="inline-flex items-center gap-2 px-8 py-3.5 rounded-full bg-ayana-primary text-white font-semibold hover:bg-ayana-primary-hover transition-colors shadow-md disabled:opacity-50">
                    Continue to activation <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
            {step === 3 && (
              <div className="text-center">
                <span className="inline-flex w-16 h-16 rounded-2xl bg-ayana-whatsapp/15 items-center justify-center mb-5"><MessageCircle className="w-8 h-8 text-ayana-whatsapp" strokeWidth={1.5} /></span>
                <h1 className="font-display text-3xl font-semibold text-ayana-text">Ready to activate their care circle</h1>
                <p className="mt-3 text-ayana-secondary max-w-lg mx-auto">We'll send a warm welcome + a short how-to-reply guide to {parentNames || "your parent"} on WhatsApp, then begin daily check-ins.</p>
                <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-3">
                  <button onClick={() => setStep(2)} className="inline-flex items-center gap-2 px-6 py-3.5 rounded-full border border-ayana-line text-ayana-text hover:bg-ayana-alt transition-colors"><ArrowLeft className="w-4 h-4" /> Edit parents</button>
                  <button onClick={activate} disabled={loading} data-testid="activate-care-circle"
                    className="inline-flex items-center gap-2 px-8 py-4 rounded-full text-white font-semibold transition-shadow shadow-lg hover:shadow-xl disabled:opacity-50"
                    style={{ background: "linear-gradient(135deg, #FF6B35, #FF8555)" }}>
                    {loading? <Loader2 className="w-4 h-4 animate-spin" /> : <>Activate Care Circle <ArrowRight className="w-4 h-4" /></>}
                  </button>
                </div>
                {loading && (
                  <p className="mt-4 text-sm text-ayana-secondary italic" data-testid="activate-pending-copy">
                    Sending the welcome WhatsApp to {parentNames || "your parent"} — this can take up to a minute. Please don't refresh.
                  </p>
                )}
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}