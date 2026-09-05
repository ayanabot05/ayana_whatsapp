import { useState, useMemo, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Users, CalendarHeart, MessageCircle, CheckCircle2, Plus, Pencil, Trash2,
  Loader2, ShieldCheck, Clock, Power, AlertTriangle, Crown, Send, UserPlus, Mail, Activity,
  RefreshCw, Check, X,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { api, formatApiError, formatAxiosError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { LANG_LABELS, TIMEZONES } from "@/lib/constants";
import { CATEGORY_ICONS, normalizeCategory } from "@/components/ScheduleEditor";
import { ParentCareForm, blankParentForm, blankMedicine } from "@/components/ParentCareForm";
import { cleanHabits, cleanOptionalString } from "@/lib/formHelpers";
import { toast } from "sonner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { CareTab } from "@/components/CareTab";
import { PricingCards } from "@/components/PricingCards";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { MonthlyReportView } from "@/components/MonthlyReportView";
import { ChangeEmailCard, ChangePasswordCard } from "@/components/SecurityCards";

function TabBoundary({ tab, onRetry, children }) {
  return (
    <ErrorBoundary
      fallback={
        <div className="rounded-xl border border-ayana-line bg-white p-6 text-center" data-testid={`tab-error-${tab}`}>
          <p className="text-sm text-ayana-secondary">This section hit a snag. Your data is safe.</p>
          <button onClick={onRetry} className="mt-3 text-sm font-medium text-ayana-accent underline underline-offset-2">Reload section</button>
        </div>
      }
    >
      {children}
    </ErrorBoundary>
  );
}

const smInputCls = "w-full px-3 py-2 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-bright/40 focus:border-ayana-bright transition";
const inputCls = "w-full px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition";

const buildFeelingMap = (feelingMap) => ({
  emoji: Object.fromEntries(Object.entries(feelingMap || {}).map(([k, v]) => [k, v.emoji])),
  label: Object.fromEntries(Object.entries(feelingMap || {}).map(([k, v]) => [k, v.label?.en || k])),
});

export default function Dashboard() {
  // NOTE: refreshUser is expected to re-fetch /auth/me and update the user
  // object in context. If AuthContext doesn't expose this yet, add a small
  // method there — the profile editor below needs it to reflect saved
  // changes without a full page reload.
  const { user, config, logout, refreshUser } = useAuth();
  const { emoji: FEELING_EMOJI, label: FEELING_LABEL } = buildFeelingMap(config?.feeling_map);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState("parents");
  const [revealedReplies, setRevealedReplies] = useState(new Set());

  // One request for the whole dashboard (was ~10 sequential round-trips).
  // Re-polls every 30s and on window focus so WhatsApp replies show up
  // without a manual refresh.
  const bootQuery = useQuery({
    queryKey: ["dashboard"],
    queryFn: () => api.get("/dashboard/bootstrap").then((r) => r.data),
    refetchInterval: 30 * 1000,
    refetchOnWindowFocus: true,
    retry: 1,
  });
  const boot = bootQuery.data;

  const parents = useMemo(() => boot?.parents ?? [], [boot]);
  const langSuggestions = useMemo(() => Object.fromEntries(
    parents.filter((p) => p.language_suggestion && p.language_suggestion !== p.language)
      .map((p) => [p.id, { suggested_language: p.language_suggestion }])
  ), [parents]);
  const schedules = boot?.schedules ?? [];
  const activation = boot?.activation ?? {};
  const payment = boot?.payment ?? { state: { plan: "nitya" } };
  const circle = boot?.circle ?? { role: "owner", members: [], invites: [] };
  const auditLogs = useMemo(() => boot?.audit ?? [], [boot]);
  const checkinsData = boot?.checkins;

  const loading = bootQuery.isLoading;
  const anyError = bootQuery.isError;

  useEffect(() => {
    if (anyError) toast.error("Could not load your data.");
  }, [anyError]);

  const load = () => queryClient.invalidateQueries({ queryKey: ["dashboard"] });

  const categories = useMemo(() => config?.categories || [], [config]);
  const relationships = config?.relationships || [];
  const languages = config?.languages || [];
  const plans = payment?.plans?.length ? payment.plans : (config?.plans || []);
  const currencies = payment?.currencies?.length ? payment.currencies : (config?.currencies || []);
  const catByKey = useMemo(() => Object.fromEntries(categories.map(normalizeCategory).map((c) => [c.key, c])), [categories]);
  const planId = payment?.state?.plan || "nitya";
  const plan = plans.find((p) => p.id === planId) || plans[0] || { id: planId, name: "AYANA Nitya", limits: {} };
  const limits = { parents: 1, checkins: 2, reminders: 2, family_members: 0, recovery_mode: false, ...(plan?.limits || {}) };
  const usage = payment?.usage || {};
  const planStatus = payment?.state?.status || "trial";
  const isMember = circle?.role === "member";
  const canAddParent = !isMember && parents.length < limits.parents;

  const relevantLogs = useMemo(() => {
    return auditLogs.filter((log) => {
      const action = (log.action || "").toLowerCase();
      return (
        action.includes("signup") ||
        action.includes("account_created") ||
        action.includes("register") ||
        action.includes("plan") ||
        action.includes("subscription") ||
        action.includes("upgrade") ||
        action.includes("downgrade") ||
        action.includes("payment")
      );
    });
  }, [auditLogs]);

  const totalMessagesSent = useMemo(() => {
    return (checkinsData?.parents || []).reduce(
      (sum, p) => sum + (p.days || []).reduce((s, d) => s + (d.total || 0), 0),
      0
    );
  }, [checkinsData]);

  const stats = [
    { icon: Users, label: "Parents", value: parents.length, color: "text-ayana-bright", bg: "rgba(255,107,53,0.12)" },
    { icon: CalendarHeart, label: "Active schedules", value: schedules.filter((s) => s.active).length, color: "text-ayana-mint", bg: "rgba(47,230,167,0.14)" },
    { icon: MessageCircle, label: "Messages sent (7d)", value: totalMessagesSent, color: "text-ayana-sky", bg: "rgba(61,184,232,0.14)" },
    { icon: CheckCircle2, label: "Care circle", value: activation.whatsapp_activated ? "Active" : "Off", color: "text-ayana-coral", bg: "rgba(255,92,122,0.12)" },
  ];

  if (loading) return (
    <div className="min-h-screen bg-ayana-bg" data-testid="dashboard-skeleton">
      <Navbar />
      <main className="max-w-6xl mx-auto px-5 sm:px-8 py-10">
        {/* Greeting skeleton */}
        <div className="mb-8 space-y-3">
          <div className="h-9 w-64 rounded-lg bg-ayana-alt animate-pulse" />
          <div className="h-4 w-96 rounded bg-ayana-alt animate-pulse" />
        </div>
        {/* Stat cards skeleton (4 cards) */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
          {[0,1,2,3].map((i) => (
            <div key={i} className="rounded-2xl border border-ayana-line bg-white p-5 space-y-3">
              <div className="w-10 h-10 rounded-xl bg-ayana-alt animate-pulse" />
              <div className="h-3 w-24 rounded bg-ayana-alt animate-pulse" />
              <div className="h-7 w-16 rounded bg-ayana-alt animate-pulse" />
            </div>
          ))}
        </div>
        {/* Tab strip skeleton */}
        <div className="flex gap-2 mb-6">
          {[0,1,2,3,4,5,6].map((i) => (
            <div key={i} className="h-9 w-24 rounded-full bg-ayana-alt animate-pulse" />
          ))}
        </div>
        {/* Main content card skeleton */}
        <div className="rounded-2xl border border-ayana-line bg-white p-6 space-y-4">
          <div className="h-5 w-40 rounded bg-ayana-alt animate-pulse" />
          <div className="space-y-3">
            <div className="h-14 w-full rounded-xl bg-ayana-alt animate-pulse" />
            <div className="h-14 w-full rounded-xl bg-ayana-alt animate-pulse" />
          </div>
        </div>
        <p className="mt-6 text-center text-xs text-ayana-secondary italic">Loading your care circle…</p>
      </main>
    </div>
  );

  return (
    <div className="min-h-screen bg-ayana-bg relative">
      <div className="absolute inset-0 pointer-events-none h-80" style={{ background: "radial-gradient(1000px 320px at 100% 0%, rgba(217,108,74,0.07), transparent), radial-gradient(800px 300px at 0% 0%, rgba(44,76,59,0.06), transparent)" }} aria-hidden="true" />
      <Navbar />
      <main className="relative max-w-6xl mx-auto px-5 sm:px-8 py-10">
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8">
          <div>
            <h1 className="font-display text-3xl font-semibold text-ayana-text">Hello, {user?.name?.split(" ")[0]} 👋</h1>
            <p className="mt-1 text-ayana-secondary flex items-center gap-2">Here's how your care circle is doing.
              <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-0.5 rounded-full capitalize ${planId !== "nitya" ? "bg-ayana-sun/20 text-[#B8860B]" : "bg-ayana-mint/20 text-[#0D9668]"}`} data-testid="plan-badge">
                {planId !== "nitya" && <Crown className="w-3 h-3" />}{plan?.name || "AYANA Nitya"} · {isMember ? "Shared" : planStatus.replace(/_/g, " ")}
              </span>
              {bootQuery.isFetching && !bootQuery.isLoading && <RefreshCw className="w-3 h-3 animate-spin text-ayana-muted" data-testid="dashboard-syncing" />}
            </p>
          </div>
          {!activation.whatsapp_activated && !user?.household_owner_id && (
            <button
              onClick={() => navigate(user?.onboarding_step >= 5 ? "/activation" : "/onboarding")}
              data-testid="finish-setup"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full text-white text-sm font-semibold shadow-md hover:shadow-lg transition-shadow"
              style={{ background: "linear-gradient(135deg, #FF6B35, #FF8555)" }}
            >
              {user?.onboarding_step >= 5 ? "Activate WhatsApp" : "Finish setup"}
            </button>
          )}
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-10" data-testid="dashboard-stats">
          {stats.map((s) => (
            <div key={s.label} className="bg-white rounded-xl border border-ayana-line p-5">
              <span className="inline-flex w-9 h-9 rounded-lg items-center justify-center mb-3" style={{ background: s.bg }}>
                <s.icon className={`w-4 h-4 ${s.color}`} strokeWidth={1.75} />
              </span>
              <p className="font-display text-2xl font-semibold text-ayana-text">{s.value}</p>
              <p className="text-sm text-ayana-muted">{s.label}</p>
            </div>
          ))}
        </div>

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="bg-ayana-alt flex w-full sm:w-auto justify-start overflow-x-auto no-scrollbar h-auto py-1">
            <TabsTrigger value="parents" data-testid="tab-parents">Parents</TabsTrigger>
            <TabsTrigger value="checkins" data-testid="tab-checkins">
              Check-ins
              {(checkinsData?.alerts?.length ?? 0) > 0 && (
                <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-red-500" title="Needs attention" />
              )}
            </TabsTrigger>
            <TabsTrigger value="reports" data-testid="tab-reports">Reports</TabsTrigger>
            <TabsTrigger value="circle" data-testid="tab-circle">Care circle</TabsTrigger>
            <TabsTrigger value="care" data-testid="tab-care">A Moment</TabsTrigger>
            <TabsTrigger value="plan" data-testid="tab-plan">Plan</TabsTrigger>
            <TabsTrigger value="account" data-testid="tab-account">Account</TabsTrigger>
          </TabsList>

          <TabsContent value="parents" className="mt-6"><TabBoundary tab="parents" onRetry={load}>
            <div className="flex justify-between items-center mb-4">
              <div>
                <h2 className="font-display text-xl font-medium text-ayana-text">Your parents</h2>
                <p className="text-xs text-ayana-muted mt-0.5" data-testid="parent-limit-note">{parents.length}/{limits.parents} parent{limits.parents > 1 ? "s" : ""} on {plan?.name?.replace("AYANA ", "") || "your plan"}</p>
              </div>
              {canAddParent ? (
                <ParentDialog relationships={relationships} languages={languages} config={config} limits={limits} plan={plan} schedules={schedules} onSaved={load}
                  trigger={<button data-testid="add-parent" className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover transition-colors"><Plus className="w-4 h-4" /> Add parent</button>} />
              ) : !isMember && (
                <button onClick={() => setActiveTab("plan")} data-testid="add-parent-upgrade" className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-ayana-line bg-white text-ayana-secondary text-sm font-medium hover:bg-ayana-alt transition-colors">
                  <Crown className="w-4 h-4 text-ayana-accent" /> {limits.parents >= 2 ? "Parent limit reached" : "Upgrade to add Nanna too"}
                </button>
              )}
            </div>
            {parents.length === 0 ? <EmptyState text="No parents added yet." /> : (
              <div className="grid sm:grid-cols-2 gap-4" data-testid="parents-list">
                {parents.map((p) => {
                  const parentSchedule = schedules.find((s) => s.parent_id === p.id);
                  const activeSchedule = parentSchedule?.active ?? true;
                  return (
                    <div key={p.id} className="bg-white rounded-xl border border-ayana-line p-5">
                      <div className="flex justify-between items-start">
                        <div>
                          <p className="font-display font-medium text-ayana-text">{p.name}</p>
                          <p className="text-sm text-ayana-muted">{p.relationship} · {LANG_LABELS[p.language]}</p>
                          {langSuggestions[p.id]?.suggested_language && (
                            <div className="mt-1 flex items-center gap-1.5">
                              <span className="text-xs px-2 py-0.5 rounded-full bg-ayana-accent/10 text-ayana-accent">
                                💡 Detected {(LANG_LABELS[langSuggestions[p.id].suggested_language] || langSuggestions[p.id].suggested_language)}
                              </span>
                              <button
                                onClick={async () => {
                                  try {
                                    await api.put(`/parents/${p.id}/language`, null, { params: { language: langSuggestions[p.id].suggested_language } });
                                    toast.success(`Language updated to ${(LANG_LABELS[langSuggestions[p.id].suggested_language] || langSuggestions[p.id].suggested_language)}.`);
                                    load();
                                  } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
                                }}
                                className="text-xs text-ayana-accent underline underline-offset-1 hover:text-ayana-accent-hover"
                                data-testid={`apply-lang-${p.id}`}
                              >
                                Apply
                              </button>
                            </div>
                          )}
                          {p.nicknames && p.nicknames.length > 0 && (
                            <p className="text-xs text-ayana-muted mt-0.5">Known as: {p.nicknames.join(", ")}</p>
                          )}
                          {p.preferred_name && (
                            <p className="text-xs text-ayana-muted italic">Called &ldquo;{p.preferred_name}&rdquo; in messages</p>
                          )}
                        </div>
                        <div className="flex gap-1">
                          <SendTestDialog parent={p} categories={categories}
                            trigger={<button data-testid={`send-test-${p.id}`} title="Send a check-in now" className="p-2 text-ayana-muted hover:text-ayana-whatsapp transition-colors"><Send className="w-4 h-4" /></button>} />
                          <ParentDialog parent={p} relationships={relationships} languages={languages} config={config} limits={limits} plan={plan} schedules={schedules} onSaved={load}
                            trigger={<button data-testid={`edit-parent-${p.id}`} title="Edit parent and schedule" className="p-2 text-ayana-muted hover:text-ayana-primary transition-colors"><Pencil className="w-4 h-4" /></button>} />
                          <ConfirmDialog onConfirm={async () => { await api.delete(`/parents/${p.id}`); toast.success("Parent removed."); load(); }}
                            trigger={<button data-testid={`delete-parent-${p.id}`} className="p-2 text-ayana-muted hover:text-red-500 transition-colors"><Trash2 className="w-4 h-4" /></button>} />
                        </div>
                      </div>
                      <div className="mt-3 space-y-2 text-sm text-ayana-secondary">
                        <p className="flex items-center gap-2"><MessageCircle className="w-3.5 h-3.5" /> {p.phone}</p>
                        <p className="flex items-center gap-2"><Clock className="w-3.5 h-3.5" /> {p.timezone}</p>
                        {parentSchedule && parentSchedule.messages && parentSchedule.messages.length > 0 && (
                          <div className="mt-2 p-2.5 bg-ayana-alt/50 rounded-lg">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-xs font-medium text-ayana-muted">Daily check-ins</span>
                              <Switch
                                checked={activeSchedule}
                                data-testid={`toggle-schedule-${parentSchedule.id}`}
                                onCheckedChange={async (v) => {
                                  await api.put(`/schedules/${parentSchedule.id}`, { parent_id: p.id, mode: parentSchedule.mode, messages: parentSchedule.messages, active: v, reengagement_hours: parentSchedule.reengagement_hours ?? 4 });
                                  load();
                                }}
                              />
                            </div>
                            <div className="flex flex-wrap gap-1.5 mt-1.5">
                              {parentSchedule.messages.filter(m => m.type !== "reminder" && m.source !== "medicine_sync").map((m, i) => {
                                const Icon = CATEGORY_ICONS[catByKey[m.category]?.icon] || MessageCircle;
                                return (
                                  <span key={i} className="inline-flex items-center gap-1 text-xs text-ayana-secondary">
                                    <Icon className="w-3 h-3 text-ayana-primary" /> {m.time} · {catByKey[m.category]?.label || m.category}
                                  </span>
                                );
                              })}
                            </div>
                          </div>
                        )}
                        {(p.medicine_list || []).length > 0 && (
                          <div className="flex flex-wrap gap-1 pt-1">
                            {(p.medicine_list || []).map((m, i) => (
                              <span key={i} className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-ayana-alt border border-ayana-line text-ayana-secondary">
                                💊 {m.name}{m.dose ? ` ${m.dose}` : ""}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </TabBoundary></TabsContent>

          <TabsContent value="checkins" className="mt-6"><TabBoundary tab="checkins" onRetry={load}>
            <CheckinsTab
              parents={parents}
              data={checkinsData}
              catByKey={catByKey}
              revealedReplies={revealedReplies}
              setRevealedReplies={setRevealedReplies}
              onAcknowledged={load}
            />
          </TabBoundary></TabsContent>

          <TabsContent value="reports" className="mt-6"><TabBoundary tab="reports" onRetry={load}>
            <ReportsTab parents={parents} plan={plan} user={user} />
          </TabBoundary></TabsContent>

          <TabsContent value="circle" className="mt-6"><TabBoundary tab="circle" onRetry={load}>
            <CircleTab circle={circle} planId={planId} plan={plan} parents={parents} reload={load} />
          </TabBoundary></TabsContent>

          <TabsContent value="care" className="mt-6"><TabBoundary tab="care" onRetry={load}>
            <CareTab parents={parents} schedules={schedules} planId={planId} limits={limits} moments={boot?.moments} quota={boot?.moments_quota} />
          </TabBoundary></TabsContent>

          <TabsContent value="plan" className="mt-6"><TabBoundary tab="plan" onRetry={load}>
            <PlanTab plans={plans} currencies={currencies} planId={planId} plan={plan} usage={usage} circle={circle} reload={load} currentBilling={payment?.state?.billing || "month"} paymentsEnabled={!!payment?.payments_enabled} />
          </TabBoundary></TabsContent>

          <TabsContent value="account" className="mt-6 max-w-xl"><TabBoundary tab="account" onRetry={load}>
            <AccountPanel user={user} plan={plan} payment={payment} circle={circle} setActiveTab={setActiveTab} refreshUser={refreshUser} />

            <div className="mt-6 grid gap-4">
              <ChangeEmailCard user={user} refreshUser={refreshUser} />
              <ChangePasswordCard />
            </div>

            <div className="mt-6 bg-white rounded-xl border border-ayana-line p-6">
              <h3 className="font-display text-lg font-medium text-ayana-text mb-4 flex items-center gap-2">Activity History</h3>
              {relevantLogs.length === 0 ? (
                <p className="text-sm text-ayana-muted">No account activity recorded yet.</p>
              ) : (
                <div className="space-y-3" data-testid="audit-log-list">
                  {relevantLogs.map((log, idx) => (
                    <div key={idx} className="flex items-start gap-3 p-3 rounded-lg bg-ayana-alt border border-ayana-line">
                      <div className="w-8 h-8 rounded-lg bg-ayana-primary/10 flex items-center justify-center shrink-0">
                        <Activity className="w-4 h-4 text-ayana-primary" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-ayana-text capitalize">{log.action.replace(/_/g, " ")}</p>
                        <p className="text-xs text-ayana-muted mt-0.5">
                          {new Date(log.created_at).toLocaleString()}
                        </p>
                        {log.meta && Object.keys(log.meta).length > 0 && (
                          <details className="mt-2">
                            <summary className="text-xs text-ayana-secondary cursor-pointer">Details</summary>
                            <pre className="mt-1 text-xs text-ayana-muted bg-white p-2 rounded overflow-x-auto">
                              {JSON.stringify(log.meta, null, 2)}
                            </pre>
                          </details>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="mt-6 bg-white rounded-xl border border-red-200 p-6">
              <h3 className="font-display text-lg font-medium text-ayana-text flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-red-500" /> Delete account</h3>
              <p className="mt-2 text-sm text-ayana-secondary">This permanently removes your account, parents, schedules, and stops all messages.</p>
              <ConfirmDialog title="Delete your account?" description="This cannot be undone. All your data and your parents' schedules will be removed." confirmLabel="Delete everything"
                onConfirm={async () => { await api.delete("/account"); toast.success("Account deleted."); logout(); navigate("/"); }}
                trigger={<button data-testid="delete-account" className="mt-4 inline-flex items-center gap-2 px-5 py-2.5 rounded-full border border-red-300 text-red-600 text-sm font-medium hover:bg-red-50 transition-colors"><Trash2 className="w-4 h-4" /> Delete my account</button>} />
            </div>
          </TabBoundary></TabsContent>
        </Tabs>
      </main>
    </div>
  );
}

// ── Fix #6: Account profile editing ─────────────────────────────────
// Was: Dashboard.js Tab 7 showed name/email/phone read-only, no edit form.
// Phone is intentionally read-only here — PUT /profile/child requires the
// submitted phone to match an OTP-verified number (see server.py
// update_child), and this editor always resends the existing, already-
// verified phone unchanged. Wiring a phone-change flow means adding the
// OTP send/verify step to this form too — out of scope for this fix, but
// straightforward to add later using the same /auth/otp/send +
// /auth/otp/verify endpoints the onboarding flow already uses.
function AccountPanel({ user, plan, payment, circle, setActiveTab, refreshUser }) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: user?.name || "", city: user?.city || "", timezone: user?.timezone || "Asia/Kolkata" });

  const startEdit = () => {
    setForm({ name: user?.name || "", city: user?.city || "", timezone: user?.timezone || "Asia/Kolkata" });
    setEditing(true);
  };

  const save = async () => {
    if (!form.name.trim()) { toast.error("Name can't be empty."); return; }
    setBusy(true);
    try {
      await api.put("/profile/child", {
        name: form.name.trim(),
        phone: user.phone, // unchanged — see note above
        city: cleanOptionalString(form.city) ?? "",
        timezone: form.timezone,
      });
      toast.success("Profile updated.");
      setEditing(false);
      if (refreshUser) {
        await refreshUser();
      }
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-ayana-line p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-display text-lg font-medium text-ayana-text">Account</h2>
        {!editing && (
          <button onClick={startEdit} data-testid="account-edit" className="inline-flex items-center gap-1.5 text-sm text-ayana-primary font-medium hover:text-ayana-primary-hover transition-colors">
            <Pencil className="w-3.5 h-3.5" /> Edit
          </button>
        )}
      </div>

      {!editing ? (
        <div className="space-y-2 text-sm text-ayana-secondary">
          <p><span className="text-ayana-muted">Name:</span> {user?.name}</p>
          <p><span className="text-ayana-muted">Email:</span> {user?.email}</p>
          <p><span className="text-ayana-muted">Phone:</span> {user?.phone}</p>
          <p><span className="text-ayana-muted">City:</span> {user?.city || "—"}</p>
          <p><span className="text-ayana-muted">Timezone:</span> {user?.timezone || "—"}</p>
          <p className="flex items-center gap-2">
            <span className="text-ayana-muted">Plan:</span> {plan?.name} · <span className="capitalize">{payment?.state?.status || "trial"}</span>
            {circle?.role !== "member" && (
              <button onClick={() => setActiveTab("plan")} data-testid="manage-plan" className="text-xs font-medium text-ayana-accent underline underline-offset-2 hover:text-ayana-accent-hover">Manage plan</button>
            )}
          </p>
          <p className="flex items-center gap-2"><ShieldCheck className="w-4 h-4 text-ayana-primary" /> Consent on file · Privacy-first</p>
        </div>
      ) : (
        <div className="space-y-4" data-testid="account-edit-form">
          <div>
            <label className="text-sm font-medium text-ayana-text">Name</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="account-edit-name" className={`mt-1.5 ${inputCls}`} />
          </div>
          <div>
            <label className="text-sm font-medium text-ayana-text">Phone</label>
            <input value={user?.phone || ""} disabled data-testid="account-edit-phone" className={`mt-1.5 ${inputCls} bg-ayana-alt/50 text-ayana-muted cursor-not-allowed`} />
            <p className="text-xs text-ayana-muted mt-1">Phone number changes aren't supported here yet — contact support if you need to update it.</p>
          </div>
          <div>
            <label className="text-sm font-medium text-ayana-text">City</label>
            <input value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} data-testid="account-edit-city" className={`mt-1.5 ${inputCls}`} />
          </div>
          <div>
            <label className="text-sm font-medium text-ayana-text">Timezone</label>
            <select value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} data-testid="account-edit-timezone" className={`mt-1.5 ${inputCls}`}>
              {TIMEZONES.map((tz) => <option key={tz.value} value={tz.value}>{tz.label}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2 pt-2">
            <button onClick={save} disabled={busy} data-testid="account-edit-save" className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} Save
            </button>
            <button onClick={() => setEditing(false)} disabled={busy} data-testid="account-edit-cancel" className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full border border-ayana-line text-ayana-secondary text-sm font-medium hover:bg-ayana-alt transition-colors">
              <X className="w-4 h-4" /> Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function CheckinsTab({ parents, data, catByKey, revealedReplies, setRevealedReplies, onAcknowledged }) {
  const [openDay, setOpenDay] = useState({});
  const [acking, setAcking] = useState(null);

  if (parents.length === 0) {
    return <EmptyState text="Add a parent first — check-ins appear here once messages start going out." />;
  }

  const parentDays = data?.parents || [];
  const alerts = data?.alerts || [];
  const toggleDay = (parentId, dayKey) => {
    const key = `${parentId}:${dayKey}`;
    setOpenDay((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const acknowledge = async (alert, idx) => {
    if (alert.kind !== "emergency") return;
    setAcking(idx);
    try {
      await api.put(`/emergency-events/${alert.event_id}`, { status: "reviewed" });
      toast.success("Marked as reviewed.");
      onAcknowledged?.();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setAcking(null);
    }
  };

  return (
    <div className="space-y-6">
      {alerts.length > 0 && (
        <div className="space-y-2" data-testid="checkins-alerts">
          {alerts.map((a, i) => (
            <div
              key={i}
              className={`rounded-xl p-3 flex items-center gap-3 text-sm border ${
                a.kind === "emergency" ? "bg-red-50 text-red-700 border-red-200" : "bg-amber-50 text-amber-700 border-amber-200"
              }`}
              data-testid={`alert-${a.kind}-${i}`}
            >
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span className="flex-1">
                {a.kind === "emergency"
                  ? `${a.parent_name} may need attention — sent "${a.body}"`
                  : `${a.parent_name} replied "need help" and hasn't been acknowledged`}
              </span>
              {a.kind === "emergency" && (
                <button
                  onClick={() => acknowledge(a, i)}
                  disabled={acking === i}
                  data-testid={`ack-${i}`}
                  className="shrink-0 text-xs font-medium px-2.5 py-1 rounded-full border border-red-300 text-red-700 hover:bg-red-100 transition-colors disabled:opacity-50"
                >
                  {acking === i ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Mark reviewed"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {parentDays.length === 0 ? (
        <div data-testid="checkins-empty">
          <EmptyState text="No check-ins delivered yet. They'll appear here once messages start going out." />
        </div>
      ) : (
        parentDays.map((pd) => {
          const today = pd.days[0];
          const rest = pd.days.slice(1);
          return (
            <div key={pd.parent_id} className="space-y-3">
              <div className="bg-white rounded-xl border border-ayana-line p-5" data-testid={`checkins-today-${pd.parent_id}`}>
                <div className="flex items-center justify-between mb-3">
                  <p className="font-display font-medium text-ayana-text">{pd.name} · today</p>
                  {today && today.total > 0 && (
                    <span
                      className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                        today.replied === today.total ? "bg-green-100 text-green-700" :
                        today.replied === 0 ? "bg-ayana-muted/15 text-ayana-muted" : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {today.replied} of {today.total} replied
                    </span>
                  )}
                </div>
                {!today || today.messages.length === 0 ? (
                  <p className="text-sm text-ayana-muted">Nothing sent yet today.</p>
                ) : (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    {today.messages.map((m) => {
                      const notSent = m.status !== "sent" && m.status !== "simulated";
                      const ok = m.reply_status === "done" || m.replied;
                      return (
                        <div key={m.id} className="bg-ayana-alt/60 rounded-lg p-2.5 text-center">
                          <p className="text-xs font-medium text-ayana-text">{catByKey[m.category]?.label || m.category}</p>
                          <p className={`text-xs mt-1 ${notSent ? "text-red-600" : ok ? "text-green-600" : "text-amber-600"}`}>
                            {notSent ? "Not sent" :
                             m.reply_status === "done" ? "Confirmed" :
                             m.reply_status === "skipped" ? "Skipped" :
                             m.replied ? `Replied ${m.time}` : `Waiting, sent ${m.time}`}
                          </p>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {rest.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  {rest.map((d) => {
                    const key = `${pd.parent_id}:${d.day_key}`;
                    const isOpen = !!openDay[key];
                    return (
                      <div key={d.day_key} className="bg-white border border-ayana-line rounded-lg overflow-hidden">
                        <button
                          onClick={() => toggleDay(pd.parent_id, d.day_key)}
                          className="w-full flex items-center justify-between px-4 py-2.5 text-sm hover:bg-ayana-alt/50 transition-colors"
                          data-testid={`day-toggle-${pd.parent_id}-${d.day_key}`}
                        >
                          <span className="text-ayana-secondary">{d.day_key}</span>
                          <span className="flex items-center gap-2">
                            <span className="flex gap-1">
                              {d.messages.map((m) => (
                                <span
                                  key={m.id}
                                  className={`w-1.5 h-1.5 rounded-full ${
                                    m.replied || m.reply_status === "done" ? "bg-green-500" :
                                    m.status !== "sent" && m.status !== "simulated" ? "bg-red-500" : "bg-ayana-muted/40"
                                  }`}
                                />
                              ))}
                            </span>
                            <span className={d.replied === d.total ? "text-green-600" : "text-ayana-muted"}>{d.replied} of {d.total}</span>
                          </span>
                        </button>
                        {isOpen && (
                          <div className="border-t border-ayana-line divide-y divide-ayana-line">
                            {d.messages.map((m) => (
                              <div key={m.id} className="px-4 py-2.5 flex items-center gap-3 text-xs">
                                <span className="text-ayana-muted w-12 shrink-0">{m.time}</span>
                                <span className="flex-1 text-ayana-text">{catByKey[m.category]?.label || m.category}</span>
                                <span className={`px-2 py-0.5 rounded-full ${m.status === "sent" || m.status === "simulated" ? "bg-ayana-whatsapp/15 text-ayana-whatsapp" : "bg-red-100 text-red-600"}`}>
                                  {m.status}
                                </span>
                                {m.replied ? (
                                  <button
                                    onClick={() =>
                                      setRevealedReplies((prev) => {
                                        const next = new Set(prev);
                                        if (next.has(m.id)) next.delete(m.id);
                                        else next.add(m.id);
                                        return next;
                                      })
                                    }
                                    className="px-2 py-0.5 rounded-full bg-green-100 text-green-700 flex items-center gap-1"
                                    aria-label={revealedReplies.has(m.id) ? "Hide reply content" : "Show reply content"}
                                  >
                                    replied
                                  </button>
                                ) : (
                                  <span className="px-2 py-0.5 rounded-full bg-ayana-muted/15 text-ayana-muted">no reply</span>
                                )}
                                {m.replied && revealedReplies.has(m.id) && m.reply?.body && (
                                  <span className="text-ayana-secondary italic truncate max-w-[160px]">&#8220;{m.reply.body}&#8221;</span>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}

function ParentDialog({ parent, config, limits, plan, schedules = [], onSaved, trigger }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [newMed, setNewMed] = useState(blankMedicine());
  const maxCheckins = limits?.checkins || 2;

  const existingSchedule = parent ? schedules.find((s) => s.parent_id === parent.id) : null;
  const getDefaultMessages = () => [
    { time: "08:00", category: "morning_wish", type: "checkin" },
    { time: "13:00", category: "lunch", type: "checkin" },
    { time: "21:00", category: "goodnight", type: "checkin" },
  ].slice(0, maxCheckins);

  const buildFormFromParent = () => {
    if (!parent) return { ...blankParentForm(), messages: getDefaultMessages(), activity_window_start: "06:00", activity_window_end: "22:00", auto_activity_detection: false };
    const sched = schedules.find((s) => s.parent_id === parent.id);
    const schedMessages = sched?.messages
      ? sched.messages.filter((m) => m.type !== "reminder" && m.source !== "medicine_sync")
      : getDefaultMessages();
    return {
      name: parent.name || "",
      relationship: parent.relationship || "mother",
      phone: parent.phone || "+91",
      language: parent.language || "en",
      timezone: parent.timezone || "Asia/Kolkata",
      notes: parent.notes || "",
      preferred_name: parent.preferred_name || "",
      nicknames: parent.nicknames || [],
      city: parent.city || "",
      other_parent_name: parent.other_parent_name || "",
      birthday: parent.birthday || "",
      stories: parent.stories || [],
      // FIXED - no more auto-detect, always 06-22
      activity_window_start: "06:00",
      activity_window_end: "22:00",
      auto_activity_detection: false,
      medicine_list: parent.medicine_list || [],
      habits: parent.habits || blankParentForm().habits,
      messages: schedMessages.length ? schedMessages : getDefaultMessages(),
      reengagement_hours: sched?.reengagement_hours ?? 4,
    };
  };
  const [form, setForm] = useState(() => buildFormFromParent());
  // If the parent was created but the schedule call failed, remember the id
  // so a retry updates that parent instead of creating a duplicate (which
  // would trip the plan's parent limit).
  const [createdParentId, setCreatedParentId] = useState(null);

  useEffect(() => {
    if (open) {
      setForm(buildFormFromParent());
      setNewMed(blankMedicine());
      setCreatedParentId(null);
    }
  // Only re-seed the form when the dialog opens. `schedules` defaults to a
  // fresh [] on every render, so depending on it caused an infinite
  // setState loop ("Maximum update depth exceeded" → "We hit a snag").
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const save = async () => {
    const checkinCount = form.messages.filter((m) => m.type !== "reminder").length;
    if (checkinCount > maxCheckins) {
      toast.error(`Your plan allows up to ${maxCheckins} check-ins. Remove some or upgrade.`);
      return;
    }
    setBusy(true);
    try {
      const { messages, reengagement_hours, ...parentData } = form;
      const payload = {
        ...parentData,
        habits: cleanHabits(form.habits),
        birthday: cleanOptionalString(form.birthday),
        // FIXED: Always 06-22, no auto-detect
        activity_window_start: "06:00",
        activity_window_end: "22:00",
        auto_activity_detection: false,
      };
      const targetId = parent?.id || createdParentId;
      const { data } = targetId ? await api.put(`/parents/${targetId}`, payload) : await api.post("/parents", payload);
      const parentId = data?.id || targetId;
      if (!parent) setCreatedParentId(parentId);

      const schedPayload = {
        parent_id: parentId,
        mode: plan?.id || "nitya",
        messages: messages,
        active: existingSchedule?.active ?? true,
        reengagement_hours: reengagement_hours ?? 4,
      };
      if (existingSchedule) {
        await api.put(`/schedules/${existingSchedule.id}`, schedPayload);
      } else if (messages.length > 0) {
        await api.post("/schedules", schedPayload);
      }

      toast.success("Saved.");
      if (data?.medicine_reminders_dropped?.length) {
        toast.warning(`Your plan couldn't fit all medicine reminder times — dropped: ${data.medicine_reminders_dropped.join(", ")}. Upgrade for more, or adjust times.`, { duration: 8000 });
      }
      setOpen(false); onSaved();
    } catch (e) { toast.error(formatAxiosError(e)); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) setNewMed(blankMedicine()); setOpen(o); }}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="bg-ayana-bg sm:max-w-2xl max-h-[85vh] overflow-y-auto overscroll-contain p-0">
        <div className="p-6">
          <DialogHeader>
            <DialogTitle className="font-display">{parent ? "Edit parent" : "Add parent"}</DialogTitle>
            <DialogDescription className="sr-only">Enter your parent's details, medicines, and routine.</DialogDescription>
          </DialogHeader>

          <div className="mt-6">
            <ParentCareForm
              form={form}
              setForm={setForm}
              newMed={newMed}
              setNewMed={setNewMed}
              config={config}
              limits={limits}
              plan={plan}
              idPrefix="pd"
            />
          </div>

          {existingSchedule && (
            <div className="flex items-center gap-2 text-xs mt-4">
              <Power className="w-4 h-4 text-ayana-muted" />
              <span className="text-ayana-secondary">Currently <span className={existingSchedule.active ? "text-green-600 font-medium" : "text-red-600 font-medium"}>{existingSchedule.active ? "active" : "paused"}</span></span>
            </div>
          )}
        </div>

        <DialogFooter className="p-6 pt-4 sticky bottom-0 bg-ayana-bg border-t border-ayana-line mt-2">
          <button onClick={save} disabled={busy || !form.name || form.phone.length < 8} data-testid="pd-save" className="inline-flex items-center gap-2 px-6 py-2.5 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50">{busy && <Loader2 className="w-4 h-4 animate-spin" />} Save</button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SendTestDialog({ parent, categories, trigger }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [category, setCategory] = useState("how_feeling");
  const send = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/messages/send-test", { parent_id: parent.id, category });
      if (data.status === "sent") toast.success(`Sent to ${parent.name} on WhatsApp ✓`);
      else if (data.status === "simulated") toast.success("Simulated (test mode) — enable WhatsApp to send for real.");
      else toast.error(`Could not send: ${data.detail || "failed"}`);
      setOpen(false);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="bg-ayana-bg max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display">Send a check-in to {parent.name} now</DialogTitle><DialogDescription className="sr-only">Pick a message and send it immediately on WhatsApp.</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <p className="text-sm text-ayana-secondary">Pick a message — it'll be sent live in {parent.name}'s language.</p>
          <select value={category} onChange={(e) => setCategory(e.target.value)} data-testid="send-test-category" className="w-full px-3.5 py-2.5 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition">
            {categories.map(normalizeCategory).map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
        </div>
        <DialogFooter>
          <button onClick={send} disabled={busy} data-testid="send-test-confirm" className="inline-flex items-center gap-2 px-6 py-2.5 rounded-full bg-ayana-whatsapp text-white text-sm font-medium hover:opacity-90 disabled:opacity-50">{busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />} Send now</button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CircleTab({ circle, planId, plan, parents, reload }) {
  const [email, setEmail] = useState("");
  const [parentId, setParentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastLink, setLastLink] = useState("");

  if (circle?.role === "member") {
    return (
      <div className="max-w-xl bg-white rounded-xl border border-ayana-line p-6">
        <h2 className="font-display text-lg font-medium text-ayana-text mb-2 flex items-center gap-2"><Users className="w-4 h-4 text-ayana-primary" /> Shared care circle</h2>
        <p className="text-sm text-ayana-secondary">You're co-caring in <b>{circle.owner?.name}</b>'s circle ({circle.owner?.email}). You can view and edit the shared parents and schedules.</p>
      </div>
    );
  }

  const planLimits = plan?.limits;
  const isCarePlus = (planLimits?.family_members || 0) > 0;
  const invite = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/circle/invite", { email, parent_id: parentId });
      setLastLink(data.invite_link || "");
      toast.success(`Invite created for ${data.email}`);
      setEmail(""); setParentId(""); reload();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); } finally { setBusy(false); }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <div className="bg-white rounded-xl border border-ayana-line p-6">
        <h2 className="font-display text-lg font-medium text-ayana-text flex items-center gap-2"><Users className="w-4 h-4 text-ayana-primary" /> Family co-care {isCarePlus && <span className="text-xs px-2 py-0.5 rounded-full bg-ayana-accent/10 text-ayana-accent inline-flex items-center gap-1"><Crown className="w-3 h-3" /> Raksha</span>}</h2>
        <p className="mt-1 text-sm text-ayana-secondary">Invite siblings to help care for the same parents. They'll share your parents, schedules and replies (but can't change billing).</p>

        {!isCarePlus ? (
          <div className="mt-4 rounded-xl bg-ayana-alt p-4 flex items-start gap-3">
            <Crown className="w-5 h-5 text-ayana-accent shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-ayana-text">Family co-care is a Raksha feature</p>
              <p className="text-sm text-ayana-secondary">Upgrade to Raksha to invite up to 2 family members.</p>
            </div>
          </div>
        ) : (
          <>
            <div className="mt-4 flex flex-col sm:flex-row gap-2" data-testid="invite-form">
              <div className="relative flex-1">
                <Mail className="w-4 h-4 text-ayana-muted absolute left-3 top-1/2 -translate-y-1/2" />
                <input value={email} onChange={(e) => setEmail(e.target.value)} data-testid="invite-email" placeholder="sibling@email.com" type="email"
                  className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-accent/50" />
              </div>
              <select value={parentId} onChange={(e) => setParentId(e.target.value)} className="w-full px-3.5 py-2.5 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition" data-testid="invite-parent-select">
                <option value="">All parents</option>
                {parents.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <button onClick={invite} disabled={busy || !email} data-testid="invite-send" className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50">{busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />} Invite</button>
            </div>
            {lastLink && <p className="mt-2 text-xs text-ayana-muted break-all">Invite link (email sending coming soon): <span className="text-ayana-primary">{lastLink}</span></p>}
            <p className="mt-2 text-xs text-ayana-muted">{(circle.members?.length || 0) + (circle.invites?.length || 0)} / {circle.max_members} members used</p>
          </>
        )}
      </div>

      {(circle.members?.length > 0 || circle.invites?.length > 0) && (
        <div className="bg-white rounded-xl border border-ayana-line divide-y divide-ayana-line" data-testid="members-list">
          {circle.members?.map((m) => (
            <div key={m.id} className="p-4 flex items-center justify-between">
              <div><p className="text-sm font-medium text-ayana-text">{m.name}</p><p className="text-xs text-ayana-muted">{m.email} · member</p></div>
              <button onClick={async () => { await api.delete(`/circle/member/${m.id}`); toast.success("Removed."); reload(); }} data-testid={`remove-member-${m.id}`} className="text-ayana-muted hover:text-red-500 p-2"><Trash2 className="w-4 h-4" /></button>
            </div>
          ))}
          {circle.invites?.map((i) => (
            <div key={i.id} className="p-4 flex items-center justify-between">
              <div><p className="text-sm text-ayana-text">{i.email}</p><p className="text-xs text-ayana-accent">pending invite</p></div>
              <button onClick={async () => { await api.delete(`/circle/invite/${i.id}`); toast.success("Invite cancelled."); reload(); }} data-testid={`cancel-invite-${i.id}`} className="text-ayana-muted hover:text-red-500 p-2"><Trash2 className="w-4 h-4" /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PlanTab({ plans, currencies, planId, plan, usage, circle, reload, currentBilling, paymentsEnabled }) {
  const [busy, setBusy] = useState(false);
  const queryClient = useQueryClient();

  if (circle?.role === "member") {
    return (
      <div className="max-w-xl bg-white rounded-xl border border-ayana-line p-6">
        <h2 className="font-display text-lg font-medium text-ayana-text mb-2 flex items-center gap-2"><Crown className="w-4 h-4 text-ayana-primary" /> Plan</h2>
        <p className="text-sm text-ayana-secondary">Only the account owner can change the plan. You're covered under <b>{circle.owner?.name}</b>'s <b>{plan?.name}</b> plan.</p>
      </div>
    );
  }

  const changePlan = async (id, billing) => {
    if (id === planId && billing === currentBilling) { toast("You're already on this plan."); return; }
    setBusy(true);
    try {
      const { data } = await api.post("/payment/checkout", { plan: id, billing, origin_url: window.location.origin });
      if (data?.checkout_url) { window.location.href = data.checkout_url; return; }
      // Optimistically reflect the new plan everywhere, then refetch for truth.
      queryClient.setQueryData(["dashboard"], (old) => old ? {
        ...old,
        payment: { ...old.payment, state: { ...(old.payment?.state || {}), plan: data?.plan || id, billing: data?.billing || billing } },
        circle: old.circle ? { ...old.circle, plan: data?.plan || id } : old.circle,
      } : old);
      toast.success(`Switched to ${plans.find((p) => p.id === id)?.name || id}. Limits updated everywhere.`);
      await reload();
    } catch (e) { toast.error(formatAxiosError(e), { duration: 8000 }); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl border border-ayana-line p-5" data-testid="plan-usage">
        <h2 className="font-display text-lg font-medium text-ayana-text mb-3">Current usage</h2>
        <div className="flex flex-wrap gap-2 text-sm">
          <span className="px-3 py-1.5 rounded-full bg-ayana-alt text-ayana-secondary">{usage.parents ?? 0}/{plan?.limits?.parents ?? "–"} parents</span>
          <span className="px-3 py-1.5 rounded-full bg-ayana-alt text-ayana-secondary">{usage.family_members_used ?? 0}/{plan?.limits?.family_members ?? 0} care-circle members</span>
          <span className="px-3 py-1.5 rounded-full bg-ayana-alt text-ayana-secondary">{plan?.limits?.checkins ?? "–"} check-ins · {plan?.limits?.reminders ?? "–"} medicine reminders / day</span>
          <span className={`px-3 py-1.5 rounded-full ${plan?.limits?.recovery_mode ? "bg-ayana-accent/10 text-ayana-accent" : "bg-ayana-alt text-ayana-muted"}`}>Recovery mode {plan?.limits?.recovery_mode ? "included" : "not included"}</span>
          {usage.recovery_schedules > 0 && <span className="px-3 py-1.5 rounded-full bg-ayana-accent/10 text-ayana-accent">Recovery mode active on {usage.recovery_schedules} schedule(s)</span>}
        </div>
        <p className="mt-3 text-xs text-ayana-muted">Downgrading below your current usage will be blocked until you free up the difference — we'll tell you exactly what to remove.{!paymentsEnabled && " Payments are in test mode: plan changes apply instantly."}</p>
      </div>

      <div className="bg-white rounded-xl border border-ayana-line p-6">
        <h2 className="font-display text-lg font-medium text-ayana-text mb-4">Change your plan</h2>
        {plans.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-8 text-center" data-testid="plans-unavailable">
            <Loader2 className="w-5 h-5 animate-spin text-ayana-muted" />
            <p className="text-sm text-ayana-secondary">Couldn't load plan options right now.</p>
            <button onClick={reload} className="text-sm font-medium text-ayana-accent underline underline-offset-2">Try again</button>
          </div>
        ) : (
          <fieldset disabled={busy}>
            <PricingCards plans={plans} currencies={currencies} selectedPlan={planId} onSelect={changePlan} compact />
          </fieldset>
        )}
      </div>
    </div>
  );
}

function ReportsTab({ parents, plan, user }) {
  return <MonthlyReportView parents={parents} plan={plan} user={user} />;
}
