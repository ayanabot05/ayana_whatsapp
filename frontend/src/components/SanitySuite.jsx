import { useEffect, useState } from "react";
import { Loader2, Send, Zap, User } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

/**
 * Admin-only live sanity suite.
 *
 * Two one-click actions against the real WhatsApp/email pipeline for a picked
 * parent — no waiting for real parent replies to verify the fixes.
 *
 *   1. "Send test welcome"  → runs services.welcomes.welcome_parent_and_child
 *      → sends ayana_opener_{lang} to parent + child. Idempotent per phone.
 *   2. "Simulate parent reply" → inserts a synthetic parent_replies row and
 *      drains the notification pipeline, so child either gets the free-form
 *      text (window open) or the ayana_parent_reply_{lang} template.
 *
 * Every delivery row (WA + email fallback) is streamed back so the operator
 * can see exactly what happened.
 */
export function SanitySuite() {
  const [parents, setParents] = useState([]);
  const [selected, setSelected] = useState("");
  const [replyBody, setReplyBody] = useState("[sanity] Amma is fine, ate lunch 💛");
  const [loading, setLoading] = useState({ list: true, welcome: false, reply: false });
  const [result, setResult] = useState(null);

  useEffect(() => {
    api.get("/admin/sanity/parents")
      .then(({ data }) => setParents(data.items || []))
      .catch(() => toast.error("Could not load parent list"))
      .finally(() => setLoading((l) => ({ ...l, list: false })));
  }, []);

  const runWelcome = async () => {
    if (!selected) return toast.error("Pick a parent first");
    setLoading((l) => ({ ...l, welcome: true }));
    setResult(null);
    try {
      const { data } = await api.post("/admin/sanity/welcome", { parent_id: selected });
      setResult({ kind: "welcome", ...data });
      toast.success("Welcome dispatched — check delivery statuses below");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to send welcome");
    } finally {
      setLoading((l) => ({ ...l, welcome: false }));
    }
  };

  const runFakeReply = async () => {
    if (!selected) return toast.error("Pick a parent first");
    setLoading((l) => ({ ...l, reply: true }));
    setResult(null);
    try {
      const { data } = await api.post("/admin/sanity/fake-reply", {
        parent_id: selected,
        body: replyBody,
      });
      setResult({ kind: "reply", ...data });
      toast.success("Fake reply dispatched — check delivery statuses below");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to simulate reply");
    } finally {
      setLoading((l) => ({ ...l, reply: false }));
    }
  };

  if (loading.list) {
    return (
      <div className="flex items-center gap-2 text-ayana-muted p-6">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading parents…
      </div>
    );
  }

  const active = parents.find((p) => p.id === selected);

  return (
    <div className="space-y-6" data-testid="sanity-suite">
      <div className="bg-white rounded-2xl border border-ayana-line p-5 space-y-4">
        <div>
          <h3 className="font-display text-lg font-semibold text-ayana-text">Live sanity suite</h3>
          <p className="text-sm text-ayana-muted mt-1">
            One-click smoke test for the WhatsApp welcome + parent-reply pipeline.
            Uses real Meta templates against real numbers — pick a parent you own.
          </p>
        </div>

        <div className="grid gap-2">
          <label className="text-xs uppercase tracking-wider text-ayana-muted">Parent</label>
          <select
            data-testid="sanity-parent-select"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="w-full rounded-lg border border-ayana-line bg-white px-3 py-2 text-sm text-ayana-text"
          >
            <option value="">— pick a parent —</option>
            {parents.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.phone} · owner {p.owner_email} ({p.owner_phone})
              </option>
            ))}
          </select>
          {active && (
            <p className="text-xs text-ayana-secondary flex items-center gap-1 mt-1">
              <User className="w-3.5 h-3.5" />
              Welcome & reply will be delivered to child <b>{active.owner_phone}</b> and parent <b>{active.phone}</b> (lang: {active.language}).
            </p>
          )}
        </div>

        <div className="grid gap-2">
          <label className="text-xs uppercase tracking-wider text-ayana-muted">Reply body (fake-reply action)</label>
          <input
            data-testid="sanity-reply-body"
            value={replyBody}
            onChange={(e) => setReplyBody(e.target.value)}
            className="w-full rounded-lg border border-ayana-line bg-white px-3 py-2 text-sm text-ayana-text"
            maxLength={600}
          />
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            data-testid="sanity-run-welcome"
            onClick={runWelcome}
            disabled={loading.welcome || !selected}
            className="inline-flex items-center gap-2 rounded-full bg-ayana-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {loading.welcome ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Send test welcome
          </button>
          <button
            data-testid="sanity-run-fake-reply"
            onClick={runFakeReply}
            disabled={loading.reply || !selected}
            className="inline-flex items-center gap-2 rounded-full bg-ayana-bright px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {loading.reply ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
            Simulate parent reply
          </button>
        </div>
      </div>

      {result && (
        <div className="bg-white rounded-2xl border border-ayana-line p-5" data-testid="sanity-result">
          <p className="text-sm font-medium text-ayana-text mb-3">
            {result.kind === "welcome" ? "Welcome delivery results" : "Reply delivery results"}
            {result.reply_id && <span className="ml-2 text-xs text-ayana-muted">reply id {result.reply_id}</span>}
          </p>
          <div className="space-y-2">
            {(result.deliveries || []).map((d, i) => (
              <div key={i} className="border border-ayana-line rounded-lg p-3 text-sm">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <span className="font-mono text-xs text-ayana-secondary">
                    {d.recipient_kind || d.event_key} → {d.phone || d.to_phone || "—"}
                  </span>
                  <StatusPill status={d.status} />
                </div>
                {d.detail && <p className="text-xs text-ayana-muted mt-1">detail: {d.detail}</p>}
                {d.error_code && <p className="text-xs text-red-500 mt-1">error_code: {d.error_code}</p>}
                {d.email_status && <p className="text-xs text-ayana-muted mt-1">email_status: {d.email_status}</p>}
                {d.sid && <p className="text-xs text-ayana-muted mt-1 font-mono">sid: {d.sid}</p>}
              </div>
            ))}
            {(!result.deliveries || result.deliveries.length === 0) && (
              <p className="text-xs text-ayana-muted">No delivery rows returned.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function StatusPill({ status }) {
  const good = ["sent", "accepted", "delivered", "read"];
  const bad = ["failed", "rejected"];
  const wait = ["pending", "retry", "awaiting_template", "uncertain", "sending"];
  const cls = good.includes(status)
    ? "bg-green-100 text-green-700"
    : bad.includes(status)
    ? "bg-red-100 text-red-700"
    : wait.includes(status)
    ? "bg-amber-100 text-amber-700"
    : "bg-ayana-alt text-ayana-muted";
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cls}`}>
      {status || "unknown"}
    </span>
  );
}
