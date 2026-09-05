import { useState, useMemo, useEffect, useCallback } from "react";
import { Loader2, RefreshCw, Crown, TrendingUp, Printer, BarChart3, CheckCircle2, Clock, MessageCircle, Smile, Pill, AlertTriangle } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { api, formatAxiosError } from "@/lib/api";
import { toast } from "sonner";
import { EmptyState } from "@/components/ui/EmptyState";

const smInputCls = "px-3 py-2 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-bright/40 focus:border-ayana-bright transition";

export const REPORT_DISCLAIMER =
  "AYANA is not an emergency or medical service. This report summarises WhatsApp check-in activity only and is not a health assessment. In a crisis, contact local emergency services or your parent's doctor immediately.";

const CATEGORY_LABELS = {
  morning_wish: "Morning hello", how_feeling: "How are you feeling", lunch: "Lunch", dinner: "Dinner",
  goodnight: "Goodnight", medicine: "Medicine reminder", tea_check: "Tea time", walk_check: "Walk",
  bp_check: "BP check", sugar_check: "Sugar check", afternoon_checkin: "Afternoon rest", reengagement: "Follow-up nudge",
};
const label = (c) => CATEGORY_LABELS[c] || (c || "").replace(/_/g, " ");

function monthLabel(period) {
  if (!period) return "";
  const [y, m] = period.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function StatCard({ icon: Icon, label: l, value, hint }) {
  return (
    <div className="bg-white rounded-xl border border-ayana-line p-4">
      <Icon className="w-4 h-4 text-ayana-primary mb-2" strokeWidth={1.75} />
      <p className="font-display text-2xl font-semibold text-ayana-text">{value ?? 0}</p>
      <p className="text-xs text-ayana-muted">{l}</p>
      {hint && <p className="text-[11px] text-ayana-muted mt-0.5">{hint}</p>}
    </div>
  );
}

export function MonthlyReportView({ parents, plan, user }) {
  const monthOptions = useMemo(() => {
    const opts = [];
    const signupDate = user?.created_at ? new Date(user.created_at) : null;
    const d = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
    while (opts.length < 12) {
      opts.push({ value: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`, label: d.toLocaleDateString(undefined, { month: "long", year: "numeric" }) });
      if (signupDate && d.getFullYear() === signupDate.getFullYear() && d.getMonth() === signupDate.getMonth()) break;
      d.setMonth(d.getMonth() - 1);
    }
    return opts;
  }, [user?.created_at]);

  const [parentId, setParentId] = useState(parents[0]?.id || "");
  const [period, setPeriod] = useState(monthOptions[0]?.value || "");
  const [report, setReport] = useState(null);
  const [status, setStatus] = useState("idle");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!parentId && parents[0]?.id) setParentId(parents[0].id);
  }, [parents, parentId]);

  const supportsMoodGraph = (plan?.limits?.variants_per_slot || 0) >= 7;

  const fetchReport = useCallback(async () => {
    if (!parentId || !period) return;
    setStatus("loading");
    try {
      const { data } = await api.get("/reports/monthly", { params: { parent_id: parentId, period } });
      if (data?.found === false) { setReport(null); setStatus("not_found"); return; }
      setReport(data);
      setStatus("idle");
    } catch (e) {
      setReport(null);
      setStatus(e.response?.status === 404 ? "not_found" : "error");
      if (e.response?.status !== 404) toast.error(formatAxiosError(e));
    }
  }, [parentId, period]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  const generate = async () => {
    if (!parentId || !period) return;
    setBusy(true);
    try {
      const { data } = await api.post("/reports/monthly/generate", null, { params: { parent_id: parentId, period } });
      setReport(data);
      setStatus("idle");
      toast.success("Report generated.");
    } catch (e) {
      toast.error(formatAxiosError(e));
    } finally { setBusy(false); }
  };

  if (parents.length === 0) {
    return <EmptyState text="Add a parent first — monthly reports appear here once check-ins start going out." />;
  }

  const parent = parents.find((p) => p.id === parentId);
  const details = report?.details || {};
  const chartData = (report?.mood_graph || []).map((p) => ({ day: p.day?.slice(8), score: p.score, feeling: p.feeling }));
  const replyRate = details.reply_rate != null ? `${Math.round(details.reply_rate * 100)}%` : "—";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3 print:hidden">
        <select value={parentId} onChange={(e) => setParentId(e.target.value)} data-testid="report-parent" className={smInputCls}>
          {parents.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select value={period} onChange={(e) => setPeriod(e.target.value)} data-testid="report-period" className={smInputCls}>
          {monthOptions.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
        <button onClick={generate} disabled={busy} data-testid="report-generate" className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-ayana-line text-ayana-text text-sm font-medium hover:bg-ayana-alt transition-colors disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />} {report ? "Regenerate" : "Generate report"}
        </button>
        {report && (
          <button onClick={() => window.print()} data-testid="report-print" className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover transition-colors">
            <Printer className="w-4 h-4" /> Download PDF
          </button>
        )}
      </div>
      <p className="text-xs text-ayana-muted flex items-center gap-1 print:hidden">
        <span className="w-1.5 h-1.5 rounded-full bg-ayana-primary" /> Reports are generated automatically on the 1st of each month for the previous month. You can also generate one now for the month so far.
      </p>

      {status === "loading" && <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-ayana-primary" /></div>}

      {status === "not_found" && (
        <div data-testid="report-empty">
          <EmptyState text="No report for this month yet. Click 'Generate report' to build one from the activity so far." />
        </div>
      )}

      {status === "idle" && report && (
        <div className="print-area relative overflow-hidden rounded-2xl border border-ayana-line bg-[#FBF6EC] p-6 sm:p-8" data-testid="report-content">
          <img src="/ayana_logo.png" alt="" aria-hidden="true" className="report-watermark pointer-events-none select-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[65%] max-w-[520px] opacity-[0.06]" />

          <div className="relative">
            <div className="flex items-start justify-between gap-4 border-b border-ayana-line pb-5">
              <div className="flex items-center gap-3">
                <img src="/ayana_logo.png" alt="AYANA" className="w-14 h-14 object-contain" />
                <div>
                  <p className="text-[11px] uppercase tracking-[0.18em] text-ayana-muted">Monthly care report</p>
                  <h3 className="font-display text-2xl font-semibold text-ayana-text" data-testid="report-title">{details.parent_name || parent?.name} · {monthLabel(report.period)}</h3>
                  <p className="text-sm text-ayana-secondary">{parent?.relationship ? `${parent.relationship} · ` : ""}{parent?.phone || ""}</p>
                </div>
              </div>
              <div className="text-right text-xs text-ayana-muted">
                <p className="inline-flex items-center gap-1 font-medium text-ayana-text"><Crown className="w-3 h-3 text-ayana-accent" /> {details.plan_name || plan?.name}</p>
                <p>Prepared for {user?.name}</p>
                <p>Generated {report.generated_at ? new Date(report.generated_at).toLocaleString() : ""}</p>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
              <StatCard icon={BarChart3} label="Messages sent" value={report.delivered} hint={`${report.total_touches ?? 0} scheduled`} />
              <StatCard icon={CheckCircle2} label="Reply rate" value={replyRate} hint={`${details.replies_total ?? 0} replies`} />
              <StatCard icon={Clock} label="Skipped" value={report.skipped} hint="quiet-hours / paused" />
              <StatCard icon={MessageCircle} label="Voice notes" value={report.voice_replies} hint={`${details.active_days ?? 0} active days`} />
            </div>

            <div className="grid sm:grid-cols-3 gap-4 mt-4">
              <div className="bg-white rounded-xl border border-ayana-line p-4">
                <p className="text-xs font-medium text-ayana-muted flex items-center gap-1.5 mb-2"><Smile className="w-3.5 h-3.5 text-ayana-primary" /> How they said they felt</p>
                <div className="flex gap-3 text-sm">
                  <span className="text-green-700">😊 {details.feelings?.good ?? 0}</span>
                  <span className="text-amber-700">😐 {details.feelings?.okay ?? 0}</span>
                  <span className="text-red-600">😟 {details.feelings?.not_well ?? 0}</span>
                </div>
              </div>
              <div className="bg-white rounded-xl border border-ayana-line p-4">
                <p className="text-xs font-medium text-ayana-muted flex items-center gap-1.5 mb-2"><Pill className="w-3.5 h-3.5 text-ayana-primary" /> Medicine</p>
                <div className="flex gap-3 text-sm">
                  <span className="text-green-700">Taken {details.medicine?.done ?? 0}</span>
                  <span className="text-ayana-muted">Skipped {details.medicine?.skipped ?? 0}</span>
                </div>
              </div>
              <div className="bg-white rounded-xl border border-ayana-line p-4">
                <p className="text-xs font-medium text-ayana-muted flex items-center gap-1.5 mb-2"><AlertTriangle className="w-3.5 h-3.5 text-ayana-primary" /> Attention alerts</p>
                <p className={`text-sm ${details.emergencies ? "text-red-600 font-medium" : "text-ayana-secondary"}`}>{details.emergencies ?? 0} flagged message{details.emergencies === 1 ? "" : "s"}</p>
              </div>
            </div>

            {supportsMoodGraph ? (
              report.mood_graph?.length > 0 ? (
                <div className="bg-white rounded-xl border border-ayana-line p-5 mt-4">
                  <h4 className="font-display text-base font-medium text-ayana-text mb-1 flex items-center gap-2"><TrendingUp className="w-4 h-4 text-ayana-primary" /> Mood this month</h4>
                  {report.trend_note && <p className="text-sm text-ayana-secondary mb-4">{report.trend_note}</p>}
                  <ResponsiveContainer width="100%" height={200}>
                    <LineChart data={chartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#E5DFD3" />
                      <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                      <YAxis domain={[0, 1]} ticks={[0, 0.5, 1]} tickFormatter={(v) => ({ 0: "Not well", 0.5: "Okay", 1: "Good" }[v] ?? v)} width={70} tick={{ fontSize: 11 }} />
                      <Tooltip formatter={(v, n, p) => [p.payload.feeling?.replace("_", " ") || "—", "Feeling"]} />
                      <Line type="monotone" dataKey="score" stroke="#C05A46" strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="bg-white rounded-xl border border-ayana-line p-4 mt-4 text-sm text-ayana-secondary">Not enough "how are you feeling" replies yet this month for a mood graph.</div>
              )
            ) : (
              <div className="rounded-xl bg-white border border-ayana-line p-4 mt-4 flex items-start gap-3 print:hidden">
                <Crown className="w-5 h-5 text-ayana-accent shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-medium text-ayana-text">Mood graph is a Bandham+ feature</p>
                  <p className="text-sm text-ayana-secondary">Upgrade for a monthly mood trend graph alongside the touch counts.</p>
                </div>
              </div>
            )}

            {details.by_category?.length > 0 && (
              <div className="bg-white rounded-xl border border-ayana-line p-5 mt-4">
                <h4 className="font-display text-base font-medium text-ayana-text mb-3">By message type</h4>
                <table className="w-full text-sm" data-testid="report-category-table">
                  <thead><tr className="text-left text-xs text-ayana-muted"><th className="pb-2 font-medium">Message</th><th className="pb-2 font-medium text-right">Sent</th><th className="pb-2 font-medium text-right">Replied</th></tr></thead>
                  <tbody className="divide-y divide-ayana-line">
                    {details.by_category.map((c) => (
                      <tr key={c.category}><td className="py-1.5 text-ayana-text">{label(c.category)}</td><td className="py-1.5 text-right text-ayana-secondary">{c.sent}</td><td className="py-1.5 text-right text-ayana-secondary">{c.replied}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {details.days?.length > 0 && (
              <div className="bg-white rounded-xl border border-ayana-line p-5 mt-4">
                <h4 className="font-display text-base font-medium text-ayana-text mb-3">Day by day</h4>
                <div className="space-y-2" data-testid="report-days">
                  {details.days.map((d) => (
                    <div key={d.day} className="flex items-start gap-3 text-xs">
                      <span className="w-20 shrink-0 text-ayana-secondary font-medium pt-0.5">{d.day.slice(5)}</span>
                      <div className="flex flex-wrap gap-1.5 flex-1">
                        {d.items.map((it, i) => (
                          <span key={i} className={`px-2 py-0.5 rounded-full border ${it.replied ? "border-green-200 bg-green-50 text-green-700" : it.status === "sent" || it.status === "simulated" ? "border-ayana-line bg-ayana-alt text-ayana-secondary" : "border-red-200 bg-red-50 text-red-600"}`}>
                            {it.time} {label(it.category)}{it.replied ? " ✓" : it.status !== "sent" && it.status !== "simulated" ? " ✕" : ""}
                          </span>
                        ))}
                      </div>
                      <span className="shrink-0 text-ayana-muted">{d.replied}/{d.sent}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {report.shared_with_care_circle && <p className="mt-4 text-xs text-ayana-muted">Shared with your Care Circle members too.</p>}

            <div className="mt-8 pt-4 border-t border-ayana-line flex items-start gap-3 text-[11px] leading-relaxed text-ayana-muted" data-testid="report-disclaimer">
              <img src="/ayana_logo.png" alt="" aria-hidden="true" className="w-6 h-6 object-contain opacity-70" />
              <p><span className="font-semibold text-ayana-secondary">Disclaimer.</span> {REPORT_DISCLAIMER} © {new Date().getFullYear()} AYANA · ayanabott.com</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
