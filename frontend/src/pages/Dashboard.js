import { useState, useMemo, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Users, CalendarHeart, MessageCircle, CheckCircle2, Plus, Pencil, Trash2,
  Loader2, ShieldCheck, Clock, Power, Crown, Send, UserPlus, Activity,
  RefreshCw, Check, X, Palmtree, Eye, EyeOff, Calendar, ChevronLeft, ChevronRight, CalendarDays,
  User, Download,
} from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { api, formatApiError, formatAxiosError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { LANG_LABELS, TIMEZONES, getBrowserTimezone } from "@/lib/constants";
import { CATEGORY_ICONS, normalizeCategory } from "@/components/ScheduleEditor";
import { ParentCareForm, blankParentForm, blankMedicine, SHAPE_ICON, COLOR_HEX } from "@/components/ParentCareForm";
import { cleanHabits, cleanOptionalString } from "@/lib/formHelpers";
import { toast } from "sonner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { PhoneInput } from "@/components/PhoneInput";
import { CareTab, VacationCard } from "@/components/CareTab";
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

// context-aware one-liner shown under each response in the Check-ins tab.
function replyContextLine(intent, parentName) {
  if (!intent) return null;
  const [action, category] = intent.split(":");
  const name = parentName || "They";
  if (action === "done" && ["medicine", "bp_check", "sugar_check", "water", "health_check"].includes(category))
    return `${name} confirmed it. One less thing to worry about.`;
  if (action === "skip" && ["breakfast", "lunch", "dinner"].includes(category))
    return `${name} skipped ${category}. Maybe give them a call this evening?`;
  if (action === "feeling" && category === "not_well")
    return `${name} isn't feeling great today. They might need to hear your voice.`;
  return null;
}

const smInputCls = "w-full px-3 py-2 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-bright/40 focus:border-ayana-bright transition";
const inputCls = "w-full px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition";

const buildFeelingMap = (feelingMap) => ({
  emoji: Object.fromEntries(Object.entries(feelingMap || {}).map(([k, v]) => [k, v.emoji])),
  label: Object.fromEntries(Object.entries(feelingMap || {}).map(([k, v]) => [k, v.label?.en || k])),
});

export default function Dashboard() {
  const { user, config, logout, refreshUser } = useAuth();
  const { emoji: FEELING_EMOJI, label: FEELING_LABEL } = buildFeelingMap(config?.feeling_map);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState("parents");
  const [revealedReplies, setRevealedReplies] = useState(new Set());

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

  // All reply toasts removed as requested - no popup like "Amma is feeling..."
  // will appear on dashboard anymore. Replies are only visible inside Check-ins tab if you open them.
  const markRepliesRead = () => {
    api.post("/replies/read", {})
      .then(() => queryClient.invalidateQueries({ queryKey: ["dashboard"] }))
      .catch(() => {});
  };

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    if (tab === "checkins") markRepliesRead();
  };

  const loading = bootQuery.isLoading;
  const anyError = bootQuery.isError;

  useEffect(() => {
    if (anyError) toast.error("Could not load your data. Please refresh the page.");
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
        <div className="mb-8 space-y-3">
          <div className="h-9 w-64 rounded-lg bg-ayana-alt animate-pulse" />
          <div className="h-4 w-96 rounded bg-ayana-alt animate-pulse" />
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
          {[0,1,2,3].map((i) => (
            <div key={i} className="rounded-2xl border border-ayana-line bg-white p-5 space-y-3">
              <div className="w-10 h-10 rounded-xl bg-ayana-alt animate-pulse" />
              <div className="h-3 w-24 rounded bg-ayana-alt animate-pulse" />
              <div className="h-7 w-16 rounded bg-ayana-alt animate-pulse" />
            </div>
          ))}
        </div>
        <div className="flex gap-2 mb-6">
          {[0,1,2,3,4,5,6].map((i) => (
            <div key={i} className="h-9 w-24 rounded-full bg-ayana-alt animate-pulse" />
          ))}
        </div>
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

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-8" data-testid="dashboard-stats">
          {stats.map((s) => (
            <div key={s.label} className="bg-white rounded-[16px] border border-[#efe8d8] p-4 sm:p-5 shadow-[0_1px_0_0_rgba(0,0,0,0.02)] hover:border-[#e6ddd0] transition-colors">
              <span className="inline-flex w-9 h-9 rounded-lg items-center justify-center mb-3" style={{ background: s.bg }}>
                <s.icon className={`w-4 h-4 ${s.color}`} strokeWidth={1.75} />
              </span>
              <p className="font-display text-2xl font-semibold text-ayana-text">{s.value}</p>
              <p className="text-sm text-ayana-muted">{s.label}</p>
            </div>
          ))}
        </div>

        <Tabs value={activeTab} onValueChange={handleTabChange}>
          <TabsList className="bg-[#faf6ec] border border-[#efe8d8] rounded-full p-1.5 flex w-full justify-start overflow-x-auto no-scrollbar h-auto gap-1 shadow-[0_1px_0_0_rgba(0,0,0,0.02)]">
            <TabsTrigger value="parents" data-testid="tab-parents">Parents</TabsTrigger>
            <TabsTrigger value="checkins" data-testid="tab-checkins">
              Check-ins
            </TabsTrigger>
            <TabsTrigger value="reports" data-testid="tab-reports">Reports</TabsTrigger>
            <TabsTrigger value="circle" data-testid="tab-circle">Care circle</TabsTrigger>
            <TabsTrigger value="care" data-testid="tab-care">A Moment</TabsTrigger>
            <TabsTrigger value="plan" data-testid="tab-plan">Plan</TabsTrigger>
            <TabsTrigger value="account" data-testid="tab-account">Account</TabsTrigger>
          </TabsList>


          <TabsContent value="parents" className="mt-6"><TabBoundary tab="parents" onRetry={load}>
            <div className="space-y-4">
              {/* Header like check-ins sample */}
              <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-[#faf6ec] border border-[#efe8d8] flex items-center justify-center">
                    <Users className="w-4 h-4 text-[#6b5f4a]" />
                  </div>
                  <div>
                    <h2 className="font-display text-[16px] font-medium text-[#1a1a1a]">Your parents</h2>
                    <p className="text-[11px] text-[#9a9183] mt-0.5" data-testid="parent-limit-note">{parents.length}/{limits.parents} parent{limits.parents > 1 ? "s" : ""} on {plan?.name?.replace("AYANA ", "") || "your plan"} • responsive on mobile</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  {canAddParent ? (
                    <ParentDialog relationships={relationships} languages={languages} config={config} limits={limits} plan={plan} schedules={schedules} onSaved={load}
                      trigger={<button data-testid="add-parent" className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-[#1a1a1a] text-white text-[13px] font-medium hover:bg-black transition-colors"><Plus className="w-4 h-4" /> Add parent</button>} />
                  ) : !isMember && (
                    <button onClick={() => setActiveTab("plan")} data-testid="add-parent-upgrade" className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full border border-[#efe8d8] bg-white text-[#6b5f4a] text-[13px] font-medium hover:bg-[#faf6ec] transition-colors">
                      <Crown className="w-4 h-4 text-[#b8860b]" /> {limits.parents >= 2 ? "Limit reached" : "Upgrade"}
                    </button>
                  )}
                </div>
              </div>

              {parents.length === 0 ? <EmptyState text="No parents added yet." /> : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="parents-list">
                  {parents.map((p) => {
                    const parentSchedule = schedules.find((s) => s.parent_id === p.id);
                    const activeSchedule = parentSchedule?.active ?? true;
                    const firstLetter = (p.name?.[0] || "A").toUpperCase();
                    return (
                      <div key={p.id} className="bg-white rounded-[16px] border border-[#efe8d8] p-4 sm:p-5 shadow-[0_1px_0_0_rgba(0,0,0,0.02)] hover:border-[#e6ddd0] transition-colors">
                        <div className="flex justify-between items-start gap-2">
                          <div className="flex gap-2.5">
                            <div className="w-9 h-9 rounded-full bg-[#f5f0e6] border border-[#efe8d8] flex items-center justify-center text-[13px] font-medium shrink-0">{firstLetter}</div>
                            <div className="min-w-0">
                              <p className="font-display font-medium text-[#1a1a1a] text-[15px] leading-none truncate">{p.name}</p>
                              <p className="text-[11px] text-[#8a7f6d] mt-1 flex items-center gap-1.5 flex-wrap">
                                <span className="px-1.5 py-0.5 rounded bg-[#faf6ec] border border-[#efe8d8]">{p.relationship}</span>
                                <span>{LANG_LABELS[p.language]}</span>
                              </p>
                            </div>
                          </div>
                          <div className="flex gap-1 shrink-0">
                            <SendTestDialog parent={p} categories={categories}
                              trigger={<button data-testid={`send-test-${p.id}`} title="Send now" className="w-8 h-8 rounded-full bg-[#faf6ec] border border-[#efe8d8] flex items-center justify-center text-[#6b5f4a] hover:bg-white"><Send className="w-3.5 h-3.5" /></button>} />
                            <ParentDialog parent={p} relationships={relationships} languages={languages} config={config} limits={limits} plan={plan} schedules={schedules} onSaved={load}
                              trigger={<button data-testid={`edit-parent-${p.id}`} title="Edit" className="w-8 h-8 rounded-full bg-white border border-[#efe8d8] flex items-center justify-center text-[#6b5f4a] hover:bg-[#faf6ec]"><Pencil className="w-3.5 h-3.5" /></button>} />
                            <ConfirmDialog onConfirm={async () => { await api.delete(`/parents/${p.id}`); toast.success("Parent removed."); load(); }}
                              trigger={<button data-testid={`delete-parent-${p.id}`} className="w-8 h-8 rounded-full bg-white border border-[#efe8d8] flex items-center justify-center text-[#9a9183] hover:text-red-500"><Trash2 className="w-3.5 h-3.5" /></button>} />
                          </div>
                        </div>
                        <div className="mt-4 space-y-2.5">
                          <div className="flex flex-col gap-1.5 text-[12px]">
                            <p className="flex items-center gap-2 text-[#6b5f4a] truncate"><MessageCircle className="w-3.5 h-3.5 text-[#9a9183] shrink-0" /> <span className="truncate">{p.phone}</span></p>
                            <p className="flex items-center gap-2 text-[#6b5f4a]"><Clock className="w-3.5 h-3.5 text-[#9a9183]" /> {p.timezone}</p>
                          </div>
                          {parentSchedule && parentSchedule.messages && parentSchedule.messages.length > 0 && (
                            <div className="p-3 bg-[#faf6ec] rounded-xl border border-[#efe8d8]">
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-[11px] font-medium text-[#8a7f6d]">Daily • {parentSchedule.messages.filter(m=>m.type!=="reminder" && m.source!=="medicine_sync").length} times</span>
                                <Switch checked={activeSchedule} data-testid={`toggle-schedule-${parentSchedule.id}`} onCheckedChange={async (v) => { await api.put(`/schedules/${parentSchedule.id}`, { parent_id: p.id, mode: parentSchedule.mode, messages: parentSchedule.messages, active: v, reengagement_hours: parentSchedule.reengagement_hours ?? 4 }); load(); }} />
                              </div>
                              <div className="flex flex-wrap gap-1.5 mt-2">
                                {parentSchedule.messages.filter(m => m.type !== "reminder" && m.source !== "medicine_sync").map((m, i) => {
                                  const Icon = CATEGORY_ICONS[catByKey[m.category]?.icon] || MessageCircle;
                                  return (
                                    <span key={i} className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-full bg-white border border-[#efe8d8] text-[#6b5f4a]">
                                      <Icon className="w-3 h-3 text-[#1a1a1a]" /> {m.time}
                                    </span>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                          {(p.medicine_list || []).length > 0 && (
                            <div className="flex flex-wrap gap-1.5">
                              {(p.medicine_list || []).map((m, i) => (
                                <span key={i} className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-full bg-white border border-[#efe8d8] text-[#6b5f4a] max-w-full truncate">
                                  {m.name}{m.dose ? ` ${m.dose}` : ""}{m.reminder_time ? ` · ${m.reminder_time}` : ""}
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

              {parents.length > 0 && (
                <div className="space-y-3">
                  <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 flex items-center gap-3">
                    <div className="w-9 h-9 rounded-full bg-[#e0f2fe] flex items-center justify-center shrink-0"><Palmtree className="w-4 h-4 text-[#0284c7]" /></div>
                    <div>
                      <h2 className="font-display text-[14px] font-medium text-[#1a1a1a]">Holiday / vacation mode</h2>
                      <p className="text-[11px] text-[#9a9183]">Pause all check-ins — resumes automatically. Mobile friendly.</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                    {parents.map((p) => <VacationCard key={p.id} parent={p} />)}
                  </div>
                </div>
              )}
            </div>
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
            <ReportsTab parents={parents} plan={plan} user={user} checkinsData={checkinsData} />
          </TabBoundary></TabsContent>

          <TabsContent value="circle" className="mt-6"><TabBoundary tab="circle" onRetry={load}>
            <CircleTab circle={circle} planId={planId} plan={plan} parents={parents} reload={load} />
          </TabBoundary></TabsContent>

          <TabsContent value="care" className="mt-6"><TabBoundary tab="care" onRetry={load}>
            <div className="space-y-4 max-w-3xl">
              <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-[#fef3c7] border border-[#fde68a] flex items-center justify-center shrink-0">💛</div>
                <div>
                  <h2 className="font-display text-[15px] font-medium text-[#1a1a1a]">A Moment - Send love instantly</h2>
                  <p className="text-[11px] text-[#9a9183]">Quick voice/text moments • Responsive on mobile</p>
                </div>
              </div>
              <div className="bg-white rounded-[16px] border border-[#efe8d8] p-2 sm:p-4">
                <CareTab parents={parents} schedules={schedules} planId={planId} limits={limits} moments={boot?.moments} quota={boot?.moments_quota} onMomentSent={load} />
              </div>
            </div>
          </TabBoundary></TabsContent>

          <TabsContent value="plan" className="mt-6"><TabBoundary tab="plan" onRetry={load}>
            <PlanTab plans={plans} currencies={currencies} planId={planId} plan={plan} usage={usage} circle={circle} parents={parents} reload={load} currentBilling={payment?.state?.billing || "month"} paymentsEnabled={!!payment?.payments_enabled} />
          </TabBoundary></TabsContent>

          <TabsContent value="account" className="mt-6 max-w-2xl"><TabBoundary tab="account" onRetry={load}>
            <div className="space-y-4">
              <AccountPanel user={user} plan={plan} payment={payment} circle={circle} setActiveTab={setActiveTab} refreshUser={refreshUser} />

              <div className="grid gap-4">
                <ChangeEmailCard user={user} refreshUser={refreshUser} />
                <ChangePasswordCard refreshUser={refreshUser} />
              </div>

              <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 sm:p-6">
                <h3 className="font-display text-[16px] font-medium text-[#1a1a1a] mb-4 flex items-center gap-2"><Activity className="w-4 h-4 text-[#0f3d2e]" /> Activity History</h3>
                {relevantLogs.length === 0 ? (
                  <p className="text-sm text-[#9a9183]">No activity yet.</p>
                ) : (
                  <div className="space-y-3" data-testid="audit-log-list">
                    {relevantLogs.map((log, idx) => (
                      <div key={log.id || idx} className="flex items-start gap-3 p-3 rounded-xl bg-[#faf6ec] border border-[#efe8d8]">
                        <div className="w-8 h-8 rounded-full bg-[#e6f4ea] border border-[#c8e9d4] flex items-center justify-center shrink-0">
                          <Activity className="w-4 h-4 text-[#0f7a4a]" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-[13px] font-medium text-[#1a1a1a] capitalize">{log.action.replace(/_/g, " ")}</p>
                          <p className="text-[11px] text-[#9a9183] mt-0.5">{new Date(log.created_at).toLocaleString()}</p>
                          {log.meta && Object.keys(log.meta).length > 0 && (
                            <details className="mt-2">
                              <summary className="text-[11px] text-[#6b5f4a] cursor-pointer">Details</summary>
                              <pre className="mt-1 text-[11px] text-[#6b5f4a] bg-white p-2 rounded-lg border border-[#efe8d8] overflow-x-auto">{JSON.stringify(log.meta, null, 2)}</pre>
                            </details>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="bg-white rounded-[16px] border border-red-100 p-4 sm:p-6">
                <h3 className="font-display text-[16px] font-medium text-[#1a1a1a] flex items-center gap-2"><Trash2 className="w-4 h-4 text-red-500" /> Delete account</h3>
                <p className="mt-2 text-[13px] text-[#6b5f4a]">This permanently removes your account, parents, schedules, and stops all messages.</p>
                <ConfirmDialog title="Delete your account?" description="This cannot be undone. All your data and your parents' schedules will be removed." confirmLabel="Delete everything"
                  onConfirm={async () => { await api.delete("/account"); toast.success("Account deleted."); logout(); navigate("/"); }}
                  trigger={<button data-testid="delete-account" className="mt-4 inline-flex items-center gap-2 px-5 py-2.5 rounded-full border border-red-200 bg-white text-red-600 text-[13px] font-medium hover:bg-red-50 transition-colors"><Trash2 className="w-4 h-4" /> Delete my account</button>} />
              </div>
            </div>
          </TabBoundary></TabsContent>

</Tabs>
      </main>
    </div>
  );
}

function AccountPanel({ user, plan, payment, circle, setActiveTab, refreshUser }) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ name: user?.name || "", city: user?.city || "", timezone: user?.timezone || getBrowserTimezone() });

  const startEdit = () => {
    setForm({ name: user?.name || "", city: user?.city || "", timezone: user?.timezone || getBrowserTimezone() });
    setEditing(true);
  };

  const save = async () => {
    if (!form.name.trim()) { toast.error("Name can't be empty."); return; }
    setBusy(true);
    try {
      await api.put("/profile/child", {
        name: form.name.trim(),
        phone: user.phone,
        city: cleanOptionalString(form.city) ?? "",
        timezone: form.timezone,
      });
      toast.success("Profile updated successfully.");
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
    <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 sm:p-6 shadow-[0_1px_0_0_rgba(0,0,0,0.02)]">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-display text-[18px] font-medium text-[#1a1a1a]">Account</h2>
        {!editing && (
          <button onClick={startEdit} data-testid="account-edit" className="inline-flex items-center gap-1.5 text-[13px] px-3 py-1.5 rounded-full bg-[#faf6ec] border border-[#efe8d8] text-[#0f3d2e] font-medium hover:bg-white transition-colors">
            <Pencil className="w-3.5 h-3.5" /> Edit
          </button>
        )}
      </div>

      {!editing ? (
        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-[13px]">
            <div className="p-3 rounded-xl bg-[#faf6ec] border border-[#efe8d8]"><p className="text-[11px] text-[#9a9183]">Name</p><p className="font-medium text-[#1a1a1a] mt-0.5">{user?.name}</p></div>
            <div className="p-3 rounded-xl bg-[#faf6ec] border border-[#efe8d8]"><p className="text-[11px] text-[#9a9183]">Email</p><p className="font-medium text-[#1a1a1a] mt-0.5 break-all">{user?.email}</p></div>
            <div className="p-3 rounded-xl bg-white border border-[#efe8d8]"><p className="text-[11px] text-[#9a9183]">Phone</p><p className="font-medium text-[#1a1a1a] mt-0.5">{user?.phone}</p></div>
            <div className="p-3 rounded-xl bg-white border border-[#efe8d8]"><p className="text-[11px] text-[#9a9183]">City</p><p className="font-medium text-[#1a1a1a] mt-0.5">{user?.city || "—"}</p></div>
            <div className="p-3 rounded-xl bg-white border border-[#efe8d8]"><p className="text-[11px] text-[#9a9183]">Timezone</p><p className="font-medium text-[#1a1a1a] mt-0.5 text-[12px]">{user?.timezone || "—"}</p></div>
            <div className="p-3 rounded-xl bg-[#0f3d2e]/5 border border-[#0f3d2e]/10"><p className="text-[11px] text-[#6b5f4a]">Plan</p><p className="font-medium text-[#1a1a1a] mt-0.5">{plan?.name} · <span className="capitalize">{payment?.state?.status || "trial"}</span> {circle?.role !== "member" && (<button onClick={() => setActiveTab("plan")} data-testid="manage-plan" className="ml-1 text-[11px] font-medium text-[#b8742a] underline underline-offset-2 hover:text-[#9a5f1f]">Manage plan</button>)}</p></div>
          </div>
          <div className="flex items-center gap-2 text-[12px] text-[#6b5f4a] bg-[#e6f4ea] border border-[#c8e9d4] rounded-full px-3 py-2 w-fit"><ShieldCheck className="w-4 h-4 text-[#0f7a4a]" /> Consent on file · Privacy-first</div>
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
            <p className="text-xs text-ayana-muted mt-1">To update phone number, please contact support.</p>
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
  // Hooks first - all before early return (fixes rules-of-hooks + mobile responsive)
  const [acking, setAcking] = useState(null);
  const [showCalendar, setShowCalendar] = useState(false);
  const [currentMonth, setCurrentMonth] = useState(() => new Date());
  const [selectedDate, setSelectedDate] = useState(() => new Date());

  const parentDays = useMemo(() => data?.parents || [], [data]);
  const alerts = useMemo(() => data?.alerts || [], [data]);

  const isoFromDate = useCallback((d) => {
    if (!d) return "";
    const dt = new Date(d);
    return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,"0")}-${String(dt.getDate()).padStart(2,"0")}`;
  }, []);

  const allDayKeys = useMemo(() => {
    const set = new Set();
    parentDays.forEach(pd => (pd.days||[]).forEach(day => set.add(day.day_key)));
    return set;
  }, [parentDays]);

  const weekDates = useMemo(() => {
    const start = new Date(selectedDate);
    start.setDate(selectedDate.getDate() - start.getDay());
    return Array.from({length:7}, (_,i) => {
      const d = new Date(start);
      d.setDate(start.getDate()+i);
      return d;
    });
  }, [selectedDate]);

  const monthStart = useMemo(() => new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 1), [currentMonth]);
  const monthEnd = useMemo(() => new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0), [currentMonth]);
  const startDay = monthStart.getDay();
  const daysInMonth = monthEnd.getDate();
  const calendarDays = useMemo(() => {
    const arr = [];
    for (let i=0;i<startDay;i++) arr.push(null);
    for (let d=1; d<=daysInMonth; d++) arr.push(d);
    return arr;
  }, [startDay, daysInMonth]);

  const getDayDataForParentByDate = useCallback((pd, date) => {
    const iso = isoFromDate(date);
    const todayIso = isoFromDate(new Date());
    const days = pd.days || [];
    if (iso === todayIso) {
      const todayData = days.find(d => d.day_key === "today");
      if (todayData) return todayData;
    }
    let found = days.find(d => d.day_key === iso);
    if (found) return found;
    found = days.find(d => String(d.day_key).includes(iso) || iso.includes(String(d.day_key)));
    return found || null;
  }, [isoFromDate]);

  const totalRepliedForSelected = useMemo(() => {
    let total = 0, replied = 0;
    parentDays.forEach(pd => {
      const dd = getDayDataForParentByDate(pd, selectedDate);
      if (dd) { total += dd.total || 0; replied += dd.replied || 0; }
    });
    return { total, replied };
  }, [parentDays, selectedDate, getDayDataForParentByDate]);

  if (parents.length === 0) {
    return <EmptyState text="Add a parent first — check-ins appear here once messages start going out." />;
  }

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

  const formatFull = (date) => {
    return date.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", year: "numeric" });
  };

  return (
    <div className="space-y-4">
      {alerts.length > 0 && (
        <div className="space-y-2">
          {alerts.map((a,i) => (
            <div key={a.id || i} className="rounded-[16px] p-3 flex items-center gap-3 text-sm border bg-white border-[#efe8d8]">
              <MessageCircle className="w-4 h-4 text-[#0f3d2e]" />
              <span className="flex-1 truncate">{a.parent_name} may need attention — {a.body}</span>
              {a.kind==="emergency" && (
                <button onClick={()=>acknowledge(a,i)} disabled={acking===i} className="shrink-0 text-xs px-2.5 py-1 rounded-full border bg-white">{acking===i ? <Loader2 className="w-3.5 h-3.5 animate-spin"/> : "Mark reviewed"}</button>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="bg-white rounded-[16px] border border-[#efe8d8] p-3 sm:p-4 shadow-[0_1px_0_0_rgba(0,0,0,0.02)]">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-full bg-[#faf6ec] border border-[#efe8d8] flex items-center justify-center shrink-0">
              <Calendar className="w-4 h-4 text-[#6b5f4a]" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <p className="font-display text-[14px] sm:text-[15px] font-medium text-[#1a1a1a] truncate">{formatFull(selectedDate)}</p>
                {isoFromDate(selectedDate) === isoFromDate(new Date()) && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#e6f4ea] text-[#1a7a4a] font-medium shrink-0">Today</span>
                )}
              </div>
              <p className="text-[11px] text-[#9a9183] mt-0.5 hidden sm:block">Tap calendar to pick any day • {parentDays.length} parents, side-by-side • mobile responsive</p>
              <p className="text-[11px] text-[#9a9183] mt-0.5 sm:hidden">{parentDays.length} parents • side-by-side</p>
            </div>
          </div>

          <div className="flex items-center gap-2 overflow-x-auto no-scrollbar">
            <div className="flex items-center gap-1 bg-[#faf6ec] rounded-full p-1 border border-[#efe8d8] shrink-0">
              {weekDates.map((d, idx) => {
                const isSelected = isoFromDate(d) === isoFromDate(selectedDate);
                const isToday = isoFromDate(d) === isoFromDate(new Date());
                const hasData = allDayKeys.has(isoFromDate(d)) || (allDayKeys.has("today") && isToday);
                return (
                  <button
                    key={idx}
                    onClick={() => setSelectedDate(d)}
                    className={`relative flex flex-col items-center justify-center min-w-[42px] sm:min-w-[44px] h-[42px] sm:h-[44px] rounded-full px-1 transition-all ${isSelected ? "bg-[#1a1a1a] text-white shadow-sm" : "text-[#6b5f4a] hover:bg-white"}`}
                  >
                    {hasData && !isSelected && <span className="absolute top-1 w-1 h-1 rounded-full bg-[#10b981]" />}
                    <span className="text-[8px] sm:text-[9px] font-medium tracking-wider opacity-70">{d.toLocaleDateString("en-US", {weekday:"short"}).toUpperCase()}</span>
                    <span className="text-[12px] sm:text-[13px] font-semibold leading-none mt-0.5">{d.getDate()}</span>
                  </button>
                );
              })}
            </div>
            <button
              onClick={() => setShowCalendar(v=>!v)}
              className={`w-9 h-9 rounded-full border flex items-center justify-center transition-colors shrink-0 ${showCalendar ? "bg-[#1a1a1a] text-white border-[#1a1a1a]" : "bg-white border-[#efe8d8] text-[#6b5f4a] hover:bg-[#faf6ec]"}`}
            >
              <Calendar className="w-4 h-4" />
            </button>
          </div>
        </div>

        {showCalendar && (
          <div className="mt-4 border-t border-[#efe8d8] pt-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="font-display text-sm font-medium">{currentMonth.toLocaleDateString("en-US", {month:"long", year:"numeric"})}</h4>
              <div className="flex gap-1">
                <button onClick={()=>setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth()-1,1))} className="w-7 h-7 rounded-full border border-[#efe8d8] bg-white flex items-center justify-center"><ChevronLeft className="w-4 h-4"/></button>
                <button onClick={()=>{setCurrentMonth(new Date()); setSelectedDate(new Date());}} className="px-2.5 h-7 rounded-full border border-[#efe8d8] bg-white text-xs">Today</button>
                <button onClick={()=>setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth()+1,1))} className="w-7 h-7 rounded-full border border-[#efe8d8] bg-white flex items-center justify-center"><ChevronRight className="w-4 h-4"/></button>
              </div>
            </div>
            <div className="grid grid-cols-7 gap-1 text-center">
              {["SUN","MON","TUE","WED","THU","FRI","SAT"].map(wd => <div key={wd} className="text-[10px] font-medium text-[#9a9183] py-1">{wd}</div>)}
              {calendarDays.map((day, idx) => {
                if (day===null) return <div key={`e-${idx}`} />;
                const dateObj = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), day);
                const iso = isoFromDate(dateObj);
                const hasData = allDayKeys.has(iso) || (allDayKeys.has("today") && iso===isoFromDate(new Date()));
                const isSelected = iso===isoFromDate(selectedDate);
                const isToday = iso===isoFromDate(new Date());
                return (
                  <button key={iso} onClick={()=>setSelectedDate(dateObj)} className={`h-9 rounded-lg text-xs font-medium flex flex-col items-center justify-center ${isSelected ? "bg-[#1a1a1a] text-white" : hasData ? "bg-[#faf6ec] text-[#1a1a1a] hover:bg-[#f0e9d8]" : "text-[#9a9183] hover:bg-[#faf6ec]"} ${isToday && !isSelected ? "ring-1 ring-[#1a1a1a] ring-offset-1" : ""}`}>
                    <span>{day}</span>{hasData && !isSelected && <span className="w-1 h-1 rounded-full bg-[#10b981] mt-0.5" />}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 px-1">
        <div className="flex items-center gap-3 text-[11px] flex-wrap">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-[#10b981] inline-block" /> <span className="text-[#6b5f4a]">Replied</span></span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-[#f59e0b] inline-block" /> <span className="text-[#9a9183]">Pending</span></span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-[#d1c7b5] inline-block" /> <span className="text-[#9a9183]">Missed</span></span>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-[#9a9183]">
          <span className="hidden sm:inline">Showing</span>
          <span className="px-2.5 py-1 rounded-full bg-white border border-[#efe8d8] text-[#1a1a1a] font-medium">{selectedDate.toLocaleDateString("en-US", {month:"short", day:"numeric"})} • {totalRepliedForSelected.replied}/{totalRepliedForSelected.total} replied</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-4">
        {parentDays.map((pd) => {
          const dayData = getDayDataForParentByDate(pd, selectedDate);
          const total = dayData?.total ?? 0;
          const replied = dayData?.replied ?? 0;
          const messages = dayData?.messages ?? [];
          const firstLetter = (pd.name?.[0] || "A").toUpperCase();
          const relLabel = pd.relationship === "mother" || pd.name?.toLowerCase().includes("amma") ? "Mother" : pd.relationship === "father" || pd.name?.toLowerCase().includes("dady") || pd.name?.toLowerCase().includes("nanna") ? "Father" : pd.relationship || "";
          return (
            <div key={pd.parent_id} className="bg-white rounded-[16px] border border-[#efe8d8] p-4 sm:p-5 shadow-[0_1px_0_0_rgba(0,0,0,0.02)] flex flex-col">
              <div className="flex items-start justify-between gap-2 mb-4">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-8 h-8 rounded-full bg-[#f5f0e6] border border-[#efe8d8] flex items-center justify-center text-[13px] font-medium text-[#1a1a1a] shrink-0">{firstLetter}</div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <p className="font-display text-[15px] sm:text-[16px] font-medium text-[#1a1a1a] leading-none truncate">{pd.name}</p>
                      {relLabel && <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#faf6ec] border border-[#efe8d8] text-[#8a7f6d] font-medium shrink-0">{relLabel}</span>}
                    </div>
                    <div className="flex items-center gap-1 mt-1 text-[11px] text-[#9a9183]">
                      <Clock className="w-3 h-3 shrink-0" />
                      <span className="truncate">{selectedDate.toLocaleDateString("en-US", {month:"short", day:"numeric"})} • 08:00 AM - 09:00 PM</span>
                    </div>
                  </div>
                </div>
                {total > 0 ? (
                  <span className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-full bg-[#e6f4ea] text-[#1a7a4a] border border-[#c8e9d4] font-medium whitespace-nowrap shrink-0">
                    <span className="w-1.5 h-1.5 rounded-full bg-[#10b981] inline-block" /> {replied} of {total}
                  </span>
                ) : (
                  <span className="text-[11px] px-2.5 py-1 rounded-full bg-[#f5f0e6] text-[#9a9183] border border-[#efe8d8] shrink-0">No msg</span>
                )}
              </div>

              {!dayData || messages.length===0 ? (
                <div className="flex-1 flex items-center justify-center py-10 bg-[#faf6ec] rounded-xl border border-dashed border-[#efe8d8] text-sm text-[#9a9183] text-center px-4">Nothing sent on this date.</div>
              ) : (
                <>
                  <div className="grid grid-cols-1 xs:grid-cols-2 sm:grid-cols-2 gap-2.5">
                    {messages.map((m) => {
                      const repliedOk = m.replied || m.reply_status==="done";
                      const time = m.time || "";
                      const label = catByKey[m.category]?.label || m.category;
                      let replyTime = "";
                      if (m.reply?.created_at) {
                        replyTime = new Date(m.reply.created_at).toLocaleTimeString("en-US", {hour:"2-digit", minute:"2-digit", hour12:true});
                      } else if (m.replied) {
                        replyTime = time;
                      }
                      return (
                        <div key={m.id} className="bg-[#fbf6ec] border border-[#efe8d8] rounded-[12px] p-3 relative hover:border-[#e6ddd0] transition-colors">
                          <div className="flex items-start justify-between">
                            <span className="text-[11px] text-[#8a7f6d] font-medium">{time}</span>
                            <span className={`w-5 h-5 rounded-full flex items-center justify-center shrink-0 ${repliedOk ? "bg-[#10b981] text-white" : "bg-white border border-[#efe8d8] text-[#d1c7b5]"}`}>
                              <Check className="w-3 h-3" strokeWidth={3} />
                            </span>
                          </div>
                          <p className="text-[13px] sm:text-[14px] font-medium text-[#1a1a1a] mt-1 leading-tight line-clamp-2">{label}</p>
                          <div className={`mt-2.5 inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] sm:text-[11px] font-medium max-w-full ${repliedOk ? "bg-[#e6f7ef] text-[#0d7a55] border border-[#c8e9d4]/60" : "bg-white text-[#9a9183] border border-[#efe8d8]"}`}>
                            <span className={`w-1 h-1 rounded-full ${repliedOk ? "bg-[#10b981]" : "bg-[#f59e0b]"} inline-block shrink-0`} />
                            <span className="truncate">{repliedOk ? `Replied ${replyTime}` : `Pending`}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="mt-4 flex items-center justify-between gap-3 pt-1">
                    <span className="text-[11px] text-[#9a9183] truncate">{replied}/{total} completed • compact</span>
                    <div className="flex-1 max-w-[100px] sm:max-w-[120px] h-1 rounded-full bg-[#f0e9d8] overflow-hidden flex shrink-0">
                      <div className="h-full bg-[#10b981] rounded-full transition-all" style={{width: `${total ? (replied/total)*100 : 0}%`}} />
                    </div>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ParentDialog({ parent, config, limits, plan, schedules = [], onSaved, trigger }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [newMed, setNewMed] = useState(blankMedicine());
  const maxCheckins = limits?.checkins || 2;
  const maxReminders = limits?.reminders || 2;

  const existingSchedule = parent ? schedules.find((s) => s.parent_id === parent.id) : null;
  const getDefaultMessages = () => [
    { time: "08:00", category: "morning_wish", type: "checkin" },
    { time: "13:00", category: "lunch", type: "checkin" },
    { time: "21:00", category: "goodnight", type: "checkin" },
  ].slice(0, maxCheckins);

  const buildFormFromParent = () => {
    if (!parent) return { ...blankParentForm(), messages: getDefaultMessages() };
    const sched = schedules.find((s) => s.parent_id === parent.id);
    const schedMessages = sched?.messages
      ? sched.messages.filter((m) => m.type !== "reminder" && m.source !== "medicine_sync")
      : getDefaultMessages();
    return {
      name: parent.name || "",
      relationship: parent.relationship || "mother",
      phone: parent.phone || "+91",
      language: parent.language || "en",
      timezone: parent.timezone || getBrowserTimezone(),
      notes: parent.notes || "",
      preferred_name: parent.preferred_name || "",
      nicknames: parent.nicknames || [],
      city: parent.city || "",
      other_parent_name: parent.other_parent_name || "",
      birthday: parent.birthday || "",
      stories: parent.stories || [],
      activity_window_start: parent.activity_window_start || "06:00",
      activity_window_end: parent.activity_window_end || "22:00",
      auto_activity_detection: false,
      medicine_list: parent.medicine_list || [],
      habits: parent.habits || blankParentForm().habits,
      messages: schedMessages.length ? schedMessages : getDefaultMessages(),
      reengagement_hours: sched?.reengagement_hours ?? 4,
    };
  };

  const [form, setForm] = useState(() => buildFormFromParent());
  const [createdParentId, setCreatedParentId] = useState(null);

  useEffect(() => {
    if (open) {
      setForm(buildFormFromParent());
      setNewMed(blankMedicine());
      setCreatedParentId(null);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const save = async () => {
    const checkinCount = form.messages.filter((m) => m.type !== "reminder").length;
    if (checkinCount > maxCheckins) {
      toast.error(`Your plan allows up to ${maxCheckins} check-ins per day. Please remove ${checkinCount - maxCheckins} or upgrade your plan.`);
      return;
    }

    let medicineListToSave = form.medicine_list || [];
    const draftName = (newMed?.name || "").trim();
    if (draftName) {
      const reminderMsgCount = form.messages.filter((m) => (m.type || "checkin") === "reminder").length;
      const currentReminderTotal = medicineListToSave.length + reminderMsgCount;
      if (currentReminderTotal >= maxReminders) {
        toast.error(`Medicine "${draftName}" not added — your plan allows ${maxReminders} medicine reminders. Please remove one first.`);
        return;
      }
      medicineListToSave = [...medicineListToSave, { ...newMed, name: draftName }];
    }

    setBusy(true);
    try {
      const { messages, reengagement_hours, medicine_list: _ignoredMedicineList, ...parentData } = form;
      const payload = {
        ...parentData,
        medicine_list: medicineListToSave,
        habits: cleanHabits(form.habits),
        birthday: cleanOptionalString(form.birthday),
        activity_window_start: cleanOptionalString(form.activity_window_start),
        activity_window_end: cleanOptionalString(form.activity_window_end),
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
        reengagement_hours: reengagement_hours ?? 1,
      };
      if (existingSchedule) {
        await api.put(`/schedules/${existingSchedule.id}`, schedPayload);
      } else if (messages.length > 0) {
        await api.post("/schedules", schedPayload);
      }

      toast.success(targetId ? "Parent details saved." : `${payload.name} is set up. First check-in tomorrow at 8:00 AM.`);
      if (data?.medicine_reminders_dropped?.length) {
        toast(`Note: Medicine times ${data.medicine_reminders_dropped.join(", ")} did not fit your plan limit (${maxReminders}). Adjust times or upgrade to include them.`, { duration: 8000 });
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
              <span className="text-ayana-secondary">Currently <span className={existingSchedule.active ? "text-green-600 font-medium" : "text-ayana-muted font-medium"}>{existingSchedule.active ? "active" : "paused"}</span></span>
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
      if (data.status === "sent") toast.success(`Message delivered to ${parent.name} on WhatsApp.`);
      else if (data.status === "simulated") toast.success("Message simulated in test mode. Enable WhatsApp to send live.");
      else toast.error(`Could not send: ${data.detail || "Please try again."}`);
      setOpen(false);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="bg-ayana-bg max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle className="font-display">Send a check-in to {parent.name} now</DialogTitle><DialogDescription className="sr-only">Pick a message and send it immediately on WhatsApp.</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <p className="text-sm text-ayana-secondary">Pick a message — it'll be sent in {parent.name}'s language.</p>
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

const SIBLING_LANGS = [["en", "English"], ["te", "తెలుగు / Telugu"], ["hi", "हिंदी / Hindi"]];

function CircleTab({ circle, planId, plan, parents, reload }) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("+91");
  const [language, setLanguage] = useState("en");
  const [step, setStep] = useState("form");
  const [code, setCode] = useState("");
  const [devCode, setDevCode] = useState("");
  const [busy, setBusy] = useState(false);

  if (circle?.role === "member") {
    return (
      <div className="max-w-xl bg-white rounded-[16px] border border-[#efe8d8] p-6">
        <h2 className="font-display text-lg font-medium text-[#1a1a1a] mb-2 flex items-center gap-2"><Users className="w-4 h-4 text-[#0f3d2e]" /> Shared care circle</h2>
        <p className="text-sm text-[#6b5f4a]">You're co-caring in <b>{circle.owner?.name}</b>'s circle ({circle.owner?.email}). You can view and edit the shared parents and schedules.</p>
      </div>
    );
  }

  const planLimits = plan?.limits;
  const isCarePlus = (planLimits?.family_members || 0) > 0;
  const siblings = circle?.siblings || [];
  const legacyMembers = circle?.members || [];
  const legacyInvites = circle?.invites || [];
  const maxMembers = circle?.max_members ?? (planLimits?.family_members || 0);
  const usedCount = siblings.length + legacyMembers.length + legacyInvites.length;
  const atLimit = usedCount >= maxMembers;
  const overLimit = usedCount > maxMembers;

  const resetForm = () => { setName(""); setPhone("+91"); setLanguage("en"); setCode(""); setDevCode(""); setStep("form"); };

  const sendOtp = async () => {
    if (!name.trim() || !phone || phone.length < 6) { toast.error("Please enter sibling name and WhatsApp number."); return; }
    setBusy(true);
    try {
      const { data } = await api.post("/circle/sibling/send-otp", { name: name.trim(), phone, language });
      setDevCode(data.dev_code || "");
      setStep("otp");
      toast.success(data.dev_code ? `Verification code: ${data.dev_code}` : "Verification code sent to WhatsApp.");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); } finally { setBusy(false); }
  };

  const verify = async () => {
    if (!code.trim()) { toast.error("Enter the 6-digit code."); return; }
    setBusy(true);
    try {
      const { data } = await api.post("/circle/sibling/verify", { name: name.trim(), phone, language, code: code.trim() });
      toast.success(`${data.sibling?.name || "Sibling"} added to your care circle.`);
      resetForm();
      reload();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); } finally { setBusy(false); }
  };

  const removeSibling = async (id) => {
    try { await api.delete(`/circle/sibling/${id}`); toast.success("Sibling removed from care circle."); reload(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 sm:p-6 shadow-[0_1px_0_0_rgba(0,0,0,0.02)]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-[#faf6ec] border border-[#efe8d8] flex items-center justify-center shrink-0"><Users className="w-4 h-4 text-[#6b5f4a]" /></div>
          <div>
            <h2 className="font-display text-[16px] font-medium text-[#1a1a1a] flex items-center gap-2">Family co-care {isCarePlus && <span className="text-[10px] px-2 py-0.5 rounded-full bg-[#fef3c7] border border-[#fde68a] text-[#92400e] inline-flex items-center gap-1"><Crown className="w-3 h-3" /> Raksha</span>}</h2>
            <p className="text-[11px] text-[#9a9183] mt-0.5">Add up to {maxMembers || 2} siblings by WhatsApp • Mobile responsive</p>
          </div>
        </div>

        {overLimit && (
          <div className="mt-4 rounded-xl bg-[#faf6ec] border border-[#efe8d8] p-4 flex items-start gap-3" data-testid="sibling-downgrade-warning">
            <Users className="w-5 h-5 text-[#6b5f4a] shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-[#1a1a1a]">Plan limit: {maxMembers} sibling{maxMembers === 1 ? "" : "s"}</p>
              <p className="text-sm text-[#6b5f4a]">You currently have {usedCount}. Please remove {usedCount - maxMembers} to match your current plan.</p>
            </div>
          </div>
        )}

        {!isCarePlus ? (
          <div className="mt-4 rounded-xl bg-[#faf6ec] border border-[#efe8d8] p-4 flex items-start gap-3">
            <Crown className="w-5 h-5 text-[#b8860b] shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-[#1a1a1a]">Family co-care is a Raksha feature</p>
              <p className="text-sm text-[#6b5f4a]">Upgrade to Raksha to add up to 2 siblings.</p>
            </div>
          </div>
        ) : atLimit && step === "form" ? (
          <p className="mt-4 text-sm text-[#9a9183]" data-testid="sibling-limit-note">You've reached your plan limit of {maxMembers} sibling{maxMembers === 1 ? "" : "s"}. Remove one to add another.</p>
        ) : step === "form" ? (
          <div className="mt-4 space-y-3" data-testid="sibling-form">
            <input value={name} onChange={(e) => setName(e.target.value)} data-testid="sibling-name" placeholder="Sibling's name (e.g. Priya)"
              className="w-full px-3.5 py-2.5 rounded-xl border border-[#efe8d8] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#0f3d2e]/20 focus:border-[#0f3d2e] transition" />
            <PhoneInput value={phone} onChange={setPhone} testid="sibling-phone" />
            <select value={language} onChange={(e) => setLanguage(e.target.value)} data-testid="sibling-language"
              className="w-full px-3.5 py-2.5 rounded-xl border border-[#efe8d8] bg-white text-sm focus:outline-none focus:ring-2 focus:ring-[#0f3d2e]/20 focus:border-[#0f3d2e] transition">
              {SIBLING_LANGS.map(([c, l]) => <option key={c} value={c}>{l}</option>)}
            </select>
            <button onClick={sendOtp} disabled={busy} data-testid="sibling-send-otp" className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-full bg-[#0f3d2e] text-white text-sm font-medium hover:bg-black transition-colors disabled:opacity-50">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />} Send verification code
            </button>
          </div>
        ) : (
          <div className="mt-4 space-y-3" data-testid="sibling-otp-step">
            <p className="text-sm text-[#6b5f4a]">Enter the 6-digit code sent to <b>{phone}</b> to add {name.trim()}.</p>
            {devCode && <p className="text-xs rounded-lg bg-[#faf6ec] border border-[#efe8d8] text-[#1a1a1a] px-3 py-2" data-testid="sibling-dev-code">Code: <b>{devCode}</b></p>}
            <input inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} data-testid="sibling-otp-code" placeholder="6-digit code"
              className="w-full px-3.5 py-2.5 rounded-xl border border-[#efe8d8] bg-white text-sm tracking-[0.3em] text-center font-semibold focus:outline-none focus:ring-2 focus:ring-[#0f3d2e]/20 focus:border-[#0f3d2e] transition" />
            <div className="flex gap-2">
              <button onClick={verify} disabled={busy} data-testid="sibling-verify" className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-full bg-[#0f3d2e] text-white text-sm font-medium hover:bg-black transition-colors disabled:opacity-50">
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />} Verify & add
              </button>
              <button onClick={resetForm} className="text-sm text-[#6b5f4a] px-3" data-testid="sibling-cancel">Cancel</button>
            </div>
          </div>
        )}
        {isCarePlus && <p className="mt-3 text-xs text-[#9a9183]" data-testid="sibling-usage">{usedCount} / {maxMembers} used</p>}
      </div>

      {(siblings.length > 0 || legacyMembers.length > 0 || legacyInvites.length > 0) && (
        <div className="bg-white rounded-[16px] border border-[#efe8d8] divide-y divide-[#efe8d8]" data-testid="siblings-list">
          {siblings.map((s) => (
            <div key={s.id} className="p-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-[#1a1a1a]">{s.name}</p>
                <p className="text-xs text-[#9a9183]">{s.phone} · {s.relation} · verified</p>
              </div>
              <ConfirmDialog
                title="Remove from care circle?"
                description={`${s.name} will stop receiving your parents' updates. You can add them back anytime.`}
                confirmLabel="Remove"
                onConfirm={() => removeSibling(s.id)}
                trigger={<button data-testid={`remove-sibling-${s.id}`} className="text-[#9a9183] hover:text-red-500 p-2"><Trash2 className="w-4 h-4" /></button>}
              />
            </div>
          ))}
          {legacyMembers.map((m) => (
            <div key={m.id} className="p-4 flex items-center justify-between">
              <div><p className="text-sm font-medium text-[#1a1a1a]">{m.name}</p><p className="text-xs text-[#9a9183]">{m.email} · member</p></div>
              <button onClick={async () => { await api.delete(`/circle/member/${m.id}`); toast.success("Member removed."); reload(); }} data-testid={`remove-member-${m.id}`} className="text-[#9a9183] hover:text-red-500 p-2"><Trash2 className="w-4 h-4" /></button>
            </div>
          ))}
          {legacyInvites.map((i) => (
            <div key={i.id} className="p-4 flex items-center justify-between">
              <div><p className="text-sm text-[#1a1a1a]">{i.email}</p><p className="text-xs text-[#9a9183]">pending invite</p></div>
              <button onClick={async () => { await api.delete(`/circle/invite/${i.id}`); toast.success("Invite cancelled."); reload(); }} data-testid={`cancel-invite-${i.id}`} className="text-[#9a9183] hover:text-red-500 p-2"><Trash2 className="w-4 h-4" /></button>
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
      <div className="max-w-xl bg-white rounded-[16px] border border-[#efe8d8] p-6">
        <h2 className="font-display text-lg font-medium text-[#1a1a1a] mb-2 flex items-center gap-2"><Crown className="w-4 h-4 text-[#0f3d2e]" /> Plan</h2>
        <p className="text-sm text-[#6b5f4a]">Only the account owner can change the plan. You're covered under <b>{circle.owner?.name}</b>'s <b>{plan?.name}</b> plan.</p>
      </div>
    );
  }
  const changePlan = async (id, billing) => {
    if (id === planId && billing === currentBilling) { toast("You're already on this plan."); return; }
    setBusy(true);
    try {
      const { data } = await api.post("/payment/checkout", { plan: id, billing, origin_url: window.location.origin });
      if (data?.checkout_url) { window.location.href = data.checkout_url; return; }
      queryClient.setQueryData(["dashboard"], (old) => old ? {
        ...old,
        payment: { ...old.payment, state: { ...(old.payment?.state || {}), plan: data?.plan || id, billing: data?.billing || billing } },
        circle: old.circle ? { ...old.circle, plan: data?.plan || id } : old.circle,
      } : old);
      toast.success(`Plan changed to ${plans.find((p) => p.id === id)?.name || id}.`);
      await reload();
    } catch (e) { toast.error(formatAxiosError(e), { duration: 8000 }); } finally { setBusy(false); }
  };
  return (
    <div className="space-y-4 max-w-3xl">
      <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-[#faf6ec] border border-[#efe8d8] flex items-center justify-center shrink-0"><Crown className="w-4 h-4 text-[#b8860b]" /></div>
        <div>
          <h2 className="font-display text-[15px] font-medium text-[#1a1a1a]">Your plan</h2>
          <p className="text-[11px] text-[#9a9183]">Usage, limits, and upgrade options • Mobile responsive</p>
        </div>
      </div>
      <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 sm:p-5" data-testid="plan-usage">
        <h2 className="font-display text-[16px] font-medium text-[#1a1a1a] mb-3">Current usage</h2>
        <div className="flex flex-wrap gap-2 text-[12px]">
          <span className="px-3 py-1.5 rounded-full bg-[#faf6ec] border border-[#efe8d8] text-[#6b5f4a]">{usage.parents ?? 0}/{plan?.limits?.parents ?? "–"} parents</span>
          <span className="px-3 py-1.5 rounded-full bg-[#faf6ec] border border-[#efe8d8] text-[#6b5f4a]">{usage.family_members_used ?? 0}/{plan?.limits?.family_members ?? 0} care-circle members</span>
          <span className="px-3 py-1.5 rounded-full bg-[#faf6ec] border border-[#efe8d8] text-[#6b5f4a]">{plan?.limits?.checkins ?? "–"} check-ins · {plan?.limits?.reminders ?? "–"} medicine reminders / day</span>
          <span className={`px-3 py-1.5 rounded-full border ${plan?.limits?.recovery_mode ? "bg-[#e6f4ea] border-[#c8e9d4] text-[#1a7a4a]" : "bg-[#faf6ec] border-[#efe8d8] text-[#9a9183]"}`}>Recovery mode {plan?.limits?.recovery_mode ? "included" : "not included"}</span>
          {usage.recovery_schedules > 0 && <span className="px-3 py-1.5 rounded-full bg-[#e6f4ea] border border-[#c8e9d4] text-[#1a7a4a]">Recovery mode active on {usage.recovery_schedules} schedule(s)</span>}
        </div>
        <p className="mt-3 text-[11px] text-[#9a9183]">Downgrading below your current usage will be blocked until you remove the extra items.</p>
      </div>
      <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 sm:p-6">
        <h2 className="font-display text-[16px] font-medium text-[#1a1a1a] mb-4">Change your plan</h2>
        {plans.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-8 text-center bg-[#faf6ec] rounded-xl border border-dashed" data-testid="plans-unavailable">
            <Loader2 className="w-5 h-5 animate-spin text-[#9a9183]" />
            <p className="text-sm text-[#6b5f4a]">Couldn't load plan options right now.</p>
            <button onClick={reload} className="text-sm font-medium text-[#0f3d2e] underline">Try again</button>
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

function ReportsTab({ parents, plan, user, checkinsData }) {
  const [selectedParentId, setSelectedParentId] = useState("all");
  const [selectedMonth, setSelectedMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [pdfBusy, setPdfBusy] = useState(false);

  const todayIso = () => new Date().toISOString().slice(0, 10);

  const monthOptions = useMemo(() => {
    const start = user?.created_at ? new Date(user.created_at) : new Date();
    const now = new Date();
    const opts = [];
    let y = start.getFullYear();
    let m = start.getMonth();
    while (y < now.getFullYear() || (y === now.getFullYear() && m <= now.getMonth())) {
      opts.push(`${y}-${String(m + 1).padStart(2, "0")}`);
      m += 1;
      if (m > 11) { m = 0; y += 1; }
    }
    return opts.reverse();
  }, [user]);

  useEffect(() => {
    if (monthOptions.length && !monthOptions.includes(selectedMonth)) {
      setSelectedMonth(monthOptions[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monthOptions]);

  const monthLabel = useMemo(() => {
    const [y, mo] = selectedMonth.split("-").map(Number);
    if (!y || !mo) return selectedMonth;
    return new Date(y, mo - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
  }, [selectedMonth]);

  const parentOptions = useMemo(() => checkinsData?.parents || [], [checkinsData]);

  const filteredParents = useMemo(() => {
    return selectedParentId === "all"
      ? parentOptions
      : parentOptions.filter((p) => p.parent_id === selectedParentId);
  }, [parentOptions, selectedParentId]);

  const filteredDays = useMemo(() => {
    const today = todayIso();
    const out = [];
    filteredParents.forEach((pd) => {
      (pd.days || []).forEach((d) => {
        const iso = d.day_key === "today" ? today : d.day_key;
        if (iso && iso.slice(0, 7) === selectedMonth) out.push({ ...d, parentName: pd.name });
      });
    });
    return out;
  }, [filteredParents, selectedMonth]);

  const allMessages = useMemo(() => filteredDays.flatMap((d) => d.messages || []), [filteredDays]);

  const stats = useMemo(() => {
    const total = allMessages.length;
    const replied = allMessages.filter((m) => m.replied || m.reply_status === "done").length;
    const skipped = allMessages.filter((m) => m.reply_status === "skipped").length;
    const voice = allMessages.filter((m) => m.reply?.is_voice).length;
    return { total, replied, skipped, voice, completion: total ? Math.round((replied / total) * 100) : 0 };
  }, [allMessages]);

  const handleDownloadPDF = async () => {
    if (!filteredParents.length) {
      toast.error("No data for selected filters");
      return;
    }
    setPdfBusy(true);
    try {
      let jsPDF = null;
      try {
        const mod = await import("jspdf");
        jsPDF = mod.jsPDF || mod.default || mod;
      } catch (e) {
        console.warn("npm jspdf not found, trying CDN", e);
      }

      if (!jsPDF) {
        if (!window.jspdf) {
          await new Promise((resolve, reject) => {
            const script = document.createElement("script");
            script.src = "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js";
            script.onload = resolve;
            script.onerror = () => reject(new Error("CDN failed"));
            document.head.appendChild(script);
          });
        }
        jsPDF = window.jspdf?.jsPDF || window.jspdf?.default || window.jspdf;
      }

      if (!jsPDF) {
        toast.error("Install jspdf: npm install jspdf in frontend folder");
        return;
      }

      const doc = new jsPDF();
      const parentName = selectedParentId === "all" ? "All-Parents" : (filteredParents[0]?.name || "Parent");

      let y = 20;
      doc.setFontSize(16);
      doc.text(`AYANA Care Report - ${parentName}`, 14, y);
      y += 8;
      doc.setFontSize(11);
      doc.text(`${monthLabel} (${selectedMonth}) | ${stats.replied}/${stats.total} = ${stats.completion}%`, 14, y);
      y += 8;
      doc.text(`Voice: ${stats.voice} | Skipped: ${stats.skipped} | Generated: ${new Date().toLocaleString()}`, 14, y);
      y += 12;

      doc.setFontSize(12);
      doc.text("By message type", 14, y);
      y += 8;
      doc.setFontSize(10);
      const byType = {};
      allMessages.forEach((m) => {
        if (!byType[m.category]) byType[m.category] = { sent: 0, done: 0 };
        byType[m.category].sent++;
        if (m.replied || m.reply_status === "done") byType[m.category].done++;
      });
      Object.entries(byType).forEach(([cat, v]) => {
        if (y > 270) { doc.addPage(); y = 20; }
        doc.text(`${cat.replace(/_/g, " ")} - ${v.done}/${v.sent}`, 14, y);
        y += 6;
      });

      y += 6;
      if (y > 250) { doc.addPage(); y = 20; }
      doc.setFontSize(12);
      doc.text("Day by day", 14, y);
      y += 8;
      doc.setFontSize(9);
      filteredDays.slice(0, 20).forEach((d) => {
        if (y > 270) { doc.addPage(); y = 20; }
        const line = `${d.day_key} - ${d.replied}/${d.total} - ${(d.messages || []).map(m => m.category).join(", ")}`;
        const split = doc.splitTextToSize(line, 180);
        doc.text(split, 14, y);
        y += split.length * 5 + 2;
      });

      doc.save(`AYANA-Report-${parentName}-${selectedMonth}.pdf`);
      toast.success(`PDF downloaded: ${parentName} - ${monthLabel}`);
    } catch (e) {
      console.error("PDF error", e);
      toast.error("PDF failed: " + e.message);
    } finally {
      setPdfBusy(false);
    }
  };

  if (parents.length === 0) {
    return <div className="p-8 text-center text-sm text-ayana-muted">Add a parent first</div>;
  }

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-[16px] border border-[#efe8d8] p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <User className="w-4 h-4 text-[#9a9183]" />
            <select
              value={selectedParentId}
              onChange={(e) => setSelectedParentId(e.target.value)}
              className="px-4 py-2 rounded-full border border-[#efe8d8] bg-white text-sm font-medium"
            >
              <option value="all">All parents</option>
              {parentOptions.map((p) => (
                <option key={p.parent_id} value={p.parent_id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-[#9a9183]" />
            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(e.target.value)}
              className="px-4 py-2 rounded-full border border-[#efe8d8] bg-white text-sm"
            >
              {monthOptions.map((m) => {
                const [y, mo] = m.split("-").map(Number);
                const label = new Date(y, mo - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
                return <option key={m} value={m}>{label}</option>;
              })}
            </select>
          </div>
          <span className="text-[11px] text-[#9a9183]">{stats.replied}/{stats.total} = {stats.completion}% • {monthLabel}</span>
        </div>
        <button
          onClick={handleDownloadPDF}
          disabled={pdfBusy}
          className="inline-flex items-center gap-1.5 px-5 py-2 rounded-full bg-[#0f3d2e] text-white text-[13px] font-medium hover:bg-black disabled:opacity-50"
        >
          {pdfBusy ? "Generating..." : <><Download className="w-4 h-4" /> Download PDF</>}
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-white rounded-[16px] border p-5"><p className="text-[28px] font-medium">{stats.total}</p><p className="text-sm text-[#6b5f4a]">Messages sent</p></div>
        <div className="bg-white rounded-[16px] border p-5"><p className="text-[28px] font-medium">{stats.completion}%</p><p className="text-sm">Completion</p></div>
        <div className="bg-white rounded-[16px] border p-5"><p className="text-[28px] font-medium">{stats.skipped}</p><p className="text-sm">Skipped</p></div>
        <div className="bg-white rounded-[16px] border p-5"><p className="text-[28px] font-medium">{stats.voice}</p><p className="text-sm">Voice notes</p></div>
      </div>
    </div>
  );
}