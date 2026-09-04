import {
  Users, Sunrise, Clock, Pill, Coffee, Heart, Utensils, Moon, Plus, Trash2,
  CalendarDays, BookOpen, VolumeX, Timer, HeartPulse,
} from "lucide-react";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { PhoneInput } from "@/components/PhoneInput";
import { ScheduleEditor, ReminderEditor } from "@/components/ScheduleEditor";
import { TIMEZONES } from "@/lib/constants";
import {
  FALLBACK_LANGUAGES, FALLBACK_RELATIONSHIPS, FALLBACK_CATEGORIES,
  FALLBACK_MEDICINE_SHAPES, FALLBACK_MEDICINE_COLORS, FALLBACK_MEDICINE_TIMINGS,
} from "@/lib/fallbackConfig";

const MONTHS = [
  { v: "01", label: "January" }, { v: "02", label: "February" }, { v: "03", label: "March" },
  { v: "04", label: "April" }, { v: "05", label: "May" }, { v: "06", label: "June" },
  { v: "07", label: "July" }, { v: "08", label: "August" }, { v: "09", label: "September" },
  { v: "10", label: "October" }, { v: "11", label: "November" }, { v: "12", label: "December" },
];

// Backend's birthday regex is (01-12)-(01-31) and doesn't validate actual
// days-per-month (so it'll technically accept "02-31") — we mirror that
// same permissiveness here rather than adding extra frontend-only rules
// that could disagree with the backend.
function daysInMonth(monthStr) {
  const days31 = ["01", "03", "05", "07", "08", "10", "12"];
  if (!monthStr) return 31;
  if (days31.includes(monthStr)) return 31;
  if (monthStr === "02") return 29; // allow leap-day entry
  return 30;
}

// ── Shared shape for a parent's form state ─────────────────────────
// Used by both Onboarding.jsx (Add a parent, step 2) and Dashboard.jsx
// (ParentDialog). Keeping this one function is what keeps a parent added
// during onboarding and a parent added from the dashboard structurally
// identical — no field either screen forgets to send.
export const blankParentForm = () => ({
  name: "",
  relationship: "mother",
  phone: "+91",
  language: "en",
  timezone: "Asia/Kolkata",
  notes: "",
  preferred_name: "",
  nicknames: [],
  city: "",
  other_parent_name: "",
  birthday: "",
  stories: [],
  activity_window_start: "",
  activity_window_end: "",
  auto_activity_detection: true,
  medicine_list: [],
  habits: {
    wake_time: "", tea_time: "", tea_type: "tea", walk_time: "",
    lunch_time: "", dinner_time: "", sleep_time: "",
  },
  // Flat list mixing checkin- and reminder-type entries — this is exactly
  // what ScheduleInput.messages is on the backend. ScheduleEditor and
  // ReminderEditor each display and edit their own subset of it.
  messages: [],
  // Schedule-level, not parent-level — ParentDialog.save() pulls this out
  // separately before sending the parent payload, same treatment as `messages`.
  reengagement_hours: 4,
});

export const blankMedicine = () => ({
  name: "", dose: "", reminder_time: "09:00", shape: "round", color: "white", timing: "after_food", notes: "",
});

const COLOR_HEX = {
  white: "#FFFFFF", cream: "#FFFDD0", yellow: "#FDE68A", orange: "#FCA347",
  pink: "#FBBFD0", red: "#F87171", purple: "#C084FC", blue: "#7DD3FC",
  green: "#86EFAC", brown: "#A07850", beige: "#D4C5A9",
};
const SHAPE_ICON = { round: "⬤", oval: "⬭", capsule: "💊", oblong: "▬", diamond: "◆", square: "■" };

const inputCls = "w-full px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-bright/50 focus:border-ayana-bright transition";
const smInputCls = "w-full px-3 py-2 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-bright/40 focus:border-ayana-bright transition";

/**
 * The actual parent-care form fields — details, check-ins, routine,
 * medicines. No dialog chrome, no save button, no consent checkbox
 * (Onboarding renders its own consent checkbox below this; Dashboard
 * doesn't need to re-collect consent on every edit).
 *
 * Mounted identically inside Onboarding's plain card and inside
 * Dashboard's <Dialog> — this is the "dynamically synced" part: fix a
 * field here once, both screens get it.
 *
 * @param form, setForm   - the parent form state (see blankParentForm)
 * @param newMed, setNewMed - the "add a medicine" draft row's state
 * @param config          - raw /config payload; fallbacks applied internally
 * @param limits          - the active plan's limits ({ checkins, reminders })
 * @param plan            - the active plan object (for display name)
 * @param idPrefix         - data-testid prefix ("parent" in onboarding,
 *                            "pd" in dashboard) so existing e2e tests keep
 *                            matching without changes
 */
export function ParentCareForm({ form, setForm, newMed, setNewMed, config, limits, plan, idPrefix = "pd" }) {
  const languages = config?.languages?.length ? config.languages : FALLBACK_LANGUAGES;
  const relationships = config?.relationships?.length ? config.relationships : FALLBACK_RELATIONSHIPS;
  const rawCategories = config?.categories?.length ? config.categories : FALLBACK_CATEGORIES;
  const shapes = config?.medicine_shapes?.length ? config.medicine_shapes : FALLBACK_MEDICINE_SHAPES;
  const colors = config?.medicine_colors?.length ? config.medicine_colors : FALLBACK_MEDICINE_COLORS;
  const timings = config?.medicine_timings?.length ? config.medicine_timings : FALLBACK_MEDICINE_TIMINGS;

  const maxCheckins = limits?.checkins || 2;
  const maxReminders = limits?.reminders || 2;

  const t = (suffix) => `${idPrefix}-${suffix}`;

  const addMedicine = () => {
    if (!newMed.name.trim()) { toast.error("Enter a medicine name."); return; }
    if ((form.medicine_list || []).length >= maxReminders) {
      toast.error(`Your ${plan?.name || "plan"} allows up to ${maxReminders} medicine reminders. Upgrade for more.`);
      return;
    }
    setForm((f) => ({ ...f, medicine_list: [...(f.medicine_list || []), { ...newMed }] }));
    setNewMed(blankMedicine());
  };
  const removeMedicine = (idx) => {
    setForm((f) => ({ ...f, medicine_list: (f.medicine_list || []).filter((_, i) => i !== idx) }));
  };
  const updateHabit = (key, val) => setForm({ ...form, habits: { ...form.habits, [key]: val } });

  // ── Birthday (MM-DD, stored as a single string on form; local state
  // holds the two halves independently so the UI reflects a half-filled
  // selection instead of collapsing back to blank between clicks).
  const [bMonth, setBMonth] = useState(() => (form.birthday || "").split("-")[0] || "");
  const [bDay, setBDay] = useState(() => (form.birthday || "").split("-")[1] || "");
  // Keep local state in sync ONLY when form.birthday is a full valid
  // MM-DD (initial mount, or switching to a different parent to edit).
  // If form.birthday is empty (user is mid-edit with only one half chosen),
  // leave local state alone so the visible dropdowns don't reset.
  useEffect(() => {
    const bday = form.birthday || "";
    if (/^\d{2}-\d{2}$/.test(bday)) {
      const [m, d] = bday.split("-");
      setBMonth(m);
      setBDay(d);
    }
  }, [form.birthday]);
  const setBirthdayPart = (part, val) => {
    const month = part === "month" ? val : bMonth;
    const day = part === "day" ? val : bDay;
    if (part === "month") setBMonth(val);
    else setBDay(val);
    // Only commit to form.birthday when both halves are set (backend
    // rejects half-filled MM-DD with a 422); otherwise clear the field
    // so old value doesn't linger.
    setForm({ ...form, birthday: month && day ? `${month}-${day}` : "" });
  };

  // ── Family stories (up to 5) ──
  const stories = form.stories || [];
  const addStory = () => {
    if (stories.length >= 5) { toast.error("Maximum 5 stories."); return; }
    setForm({ ...form, stories: [...stories, ""] });
  };
  const updateStory = (idx, val) => {
    const next = [...stories]; next[idx] = val;
    setForm({ ...form, stories: next });
  };
  const removeStory = (idx) => {
    setForm({ ...form, stories: stories.filter((_, i) => i !== idx) });
  };

  return (
    <div className="space-y-10">
      {/* ── Section 1: Parent details ── */}
      <section className="space-y-5">
        <div className="flex items-center gap-2 pb-2 border-b border-ayana-line/50">
          <Users className="w-4.5 h-4.5 text-ayana-primary" />
          <h4 className="font-display font-medium text-ayana-text">1. Parent details</h4>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-medium text-ayana-text">Their name</label>
            <input value={form.name} data-testid={t("name")} onChange={(e) => setForm({ ...form, name: e.target.value })} className={`mt-1.5 ${inputCls}`} placeholder="Amma" />
          </div>
          <div>
            <label className="text-sm font-medium text-ayana-text">Relationship</label>
            <select value={form.relationship} data-testid={t("relationship")} onChange={(e) => setForm({ ...form, relationship: e.target.value })} className={`mt-1.5 ${inputCls}`}>
              {relationships.map((r) => {
                const val = typeof r === "string" ? r : r.value;
                const label = typeof r === "string" ? (val.charAt(0).toUpperCase() + val.slice(1)) : r.label;
                return <option key={val} value={val}>{label}</option>;
              })}
            </select>
          </div>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-medium text-ayana-text">WhatsApp number</label>
            <div className="mt-1.5"><PhoneInput value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} testid={t("phone")} /></div>
          </div>
          <div>
            <label className="text-sm font-medium text-ayana-text">Preferred language</label>
            <select value={form.language} data-testid={t("language")} onChange={(e) => setForm({ ...form, language: e.target.value })} className={`mt-1.5 ${inputCls}`}>
              {languages.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
            </select>
          </div>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-medium text-ayana-text">Their timezone</label>
            <select value={form.timezone} data-testid={t("timezone")} onChange={(e) => setForm({ ...form, timezone: e.target.value })} className={`mt-1.5 ${inputCls}`}>
              {TIMEZONES.map((tz) => <option key={tz.value} value={tz.value}>{tz.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-sm font-medium text-ayana-text">Their city (optional)</label>
            <input value={form.city || ""} onChange={(e) => setForm({ ...form, city: e.target.value })} data-testid={t("city")} placeholder="Hyderabad" className={`mt-1.5 ${inputCls}`} />
          </div>
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-medium text-ayana-text">Preferred name (nickname for messages)</label>
            <input value={form.preferred_name || ""} onChange={(e) => setForm({ ...form, preferred_name: e.target.value })} data-testid={t("preferred-name")} placeholder="e.g. Amma" className={`mt-1.5 ${inputCls}`} />
          </div>
          <div>
            <label className="text-sm font-medium text-ayana-text">Other parent's name (optional)</label>
            <input value={form.other_parent_name || ""} onChange={(e) => setForm({ ...form, other_parent_name: e.target.value })} data-testid={t("other-parent-name")} placeholder="e.g. Ramesh" className={`mt-1.5 ${inputCls}`} />
            <p className="text-xs text-ayana-muted mt-1">Used when a message asks "did {'{'}other parent{'}'} eat too?"</p>
          </div>
        </div>
        <div>
          <label className="text-sm font-medium text-ayana-text">Nicknames (comma-separated)</label>
          <input
            value={(form.nicknames || []).join(", ")}
            onChange={(e) => setForm({ ...form, nicknames: e.target.value.split(",").map((n) => n.trim()).filter(Boolean).slice(0, 3) })}
            data-testid={t("nicknames")}
            placeholder="e.g. Amma, Mummy"
            className={`mt-1.5 ${inputCls}`}
          />
          <p className="text-xs text-ayana-muted mt-1">Max 3 nicknames — AYANA rotates between these day to day so messages don't repeat. Leave blank to just reuse the preferred name above.</p>
        </div>

        {/* Birthday — unlocks the birthday auto-wish in escalation.py */}
        <div>
          <label className="text-sm font-medium text-ayana-text flex items-center gap-1.5">
            <CalendarDays className="w-3.5 h-3.5 text-ayana-primary" /> Birthday (optional)
          </label>
          <div className="mt-1.5 grid grid-cols-2 gap-3 max-w-sm">
            <select value={bMonth || ""} onChange={(e) => setBirthdayPart("month", e.target.value)} data-testid={t("birthday-month")} className={inputCls}>
              <option value="">Month</option>
              {MONTHS.map((m) => <option key={m.v} value={m.v}>{m.label}</option>)}
            </select>
            <select value={bDay || ""} onChange={(e) => setBirthdayPart("day", e.target.value)} data-testid={t("birthday-day")} className={inputCls}>
              <option value="">Day</option>
              {Array.from({ length: daysInMonth(bMonth) }, (_, i) => String(i + 1).padStart(2, "0")).map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>
          <p className="text-xs text-ayana-muted mt-1">AYANA sends a special birthday wish in their language — no year needed, just month and day.</p>
        </div>

        {/* Family stories — woven into rotating message bodies */}
        <div>
          <label className="text-sm font-medium text-ayana-text flex items-center gap-1.5">
            <BookOpen className="w-3.5 h-3.5 text-ayana-primary" /> Family stories (optional)
          </label>
          <p className="text-xs text-ayana-muted mt-1 mb-2">Short memories AYANA can weave into messages — e.g. "Remember when we went to Tirupati?" Up to 5.</p>
          <div className="space-y-2">
            {stories.map((s, idx) => (
              <div key={idx} className="flex items-start gap-2">
                <textarea
                  value={s}
                  onChange={(e) => updateStory(idx, e.target.value.slice(0, 200))}
                  data-testid={t(`story-${idx}`)}
                  placeholder="A short family memory…"
                  rows={2}
                  className={`${inputCls} resize-none text-sm flex-1`}
                />
                <button onClick={() => removeStory(idx)} data-testid={t(`story-remove-${idx}`)} className="mt-2 text-ayana-muted hover:text-red-500 shrink-0">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
          {stories.length < 5 && (
            <button onClick={addStory} data-testid={t("story-add")} className="mt-2 inline-flex items-center gap-1.5 text-sm text-ayana-primary font-medium hover:text-ayana-primary-hover transition-colors">
              <Plus className="w-4 h-4" /> Add a story
            </button>
          )}
        </div>
      </section>

      {/* ── Section 2: Daily check-ins ── */}
      <section className="space-y-5">
        <div className="flex items-center justify-between pb-2 border-b border-ayana-line/50">
          <div className="flex items-center gap-2">
            <Sunrise className="w-4.5 h-4.5 text-ayana-bright" />
            <h4 className="font-display font-medium text-ayana-text">2. Daily check-ins</h4>
          </div>
          <span className="text-xs text-ayana-muted">{(form.messages || []).filter((m) => (m.type || "checkin") === "checkin").length}/{maxCheckins} used · {plan?.name}</span>
        </div>
        <ScheduleEditor
          messages={form.messages || []}
          setMessages={(msgs) => setForm({ ...form, messages: msgs })}
          categories={rawCategories}
          maxCheckins={maxCheckins}
        />
        <div className="flex items-center gap-3 pt-1">
          <label className="text-xs font-medium text-ayana-secondary flex items-center gap-1.5">
            <Timer className="w-3.5 h-3.5" /> If they don't reply, check again after
          </label>
          <select
            value={form.reengagement_hours ?? 4}
            onChange={(e) => setForm({ ...form, reengagement_hours: Number(e.target.value) })}
            data-testid={t("reengagement-hours")}
            className={`${smInputCls} w-auto`}
          >
            {[1, 2, 3, 4, 6, 8, 12, 24].map((h) => <option key={h} value={h}>{h} hour{h > 1 ? "s" : ""}</option>)}
          </select>
        </div>

        {/* Health reminders — water / BP / sugar / general. Share the plan's
            reminder quota with the Medicine section below, so the counter
            here reflects both. */}
        <div className="pt-4 border-t border-ayana-line/50">
          <div className="flex items-center justify-between mb-2">
            <label className="text-sm font-medium text-ayana-text flex items-center gap-1.5">
              <HeartPulse className="w-3.5 h-3.5 text-ayana-primary" /> Health reminders (optional)
            </label>
            <span className="text-xs text-ayana-muted">
              {(form.messages || []).filter((m) => (m.type || "checkin") === "reminder").length + (form.medicine_list || []).length}/{maxReminders} reminders used
            </span>
          </div>
          <p className="text-xs text-ayana-secondary mb-2">Water, BP check, sugar check, or a general health check — these don't need a medicine name, just a time.</p>
          <ReminderEditor
            messages={form.messages || []}
            setMessages={(msgs) => setForm({ ...form, messages: msgs })}
            categories={rawCategories}
            maxReminders={maxReminders}
            medicineCount={(form.medicine_list || []).length}
          />
        </div>
      </section>

      {/* ── Section 3: Daily routine & activities ── */}
      <section className="space-y-5">
        <div className="flex items-center gap-2 pb-2 border-b border-ayana-line/50">
          <Clock className="w-4.5 h-4.5 text-ayana-mint" />
          <h4 className="font-display font-medium text-ayana-text">3. Daily routine & activities</h4>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
          {[
            { id: "wake_time", label: "Wake up", icon: Sunrise },
            { id: "tea_time", label: "Tea / Coffee", icon: Coffee },
            { id: "walk_time", label: "Walk", icon: Heart },
            { id: "lunch_time", label: "Lunch", icon: Utensils },
            { id: "dinner_time", label: "Dinner", icon: Utensils },
            { id: "sleep_time", label: "Sleep", icon: Moon },
          ].map((h) => (
            <div key={h.id}>
              <label className="text-xs font-medium text-ayana-secondary flex items-center gap-1 mb-1.5">
                <h.icon className="w-3 h-3" /> {h.label}
              </label>
              <input type="time" value={form.habits?.[h.id] || ""} onChange={(e) => updateHabit(h.id, e.target.value)} data-testid={t(`habit-${h.id}`)} className={smInputCls} />
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3 px-1">
          <span className="text-xs font-medium text-ayana-secondary">Prefers:</span>
          {["tea", "coffee"].map((tt) => (
            <button key={tt} type="button" onClick={() => updateHabit("tea_type", tt)}
              className={`px-3.5 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                form.habits?.tea_type === tt
                  ? "bg-ayana-primary text-white border-ayana-primary"
                  : "bg-white text-ayana-secondary border-ayana-line hover:bg-ayana-alt"
              }`}>
              {tt === "tea" ? "☕ Tea" : "☕ Coffee"}
            </button>
          ))}
        </div>
        <p className="text-xs text-ayana-muted italic px-1">Routine times personalize message content (e.g. "Hope you had your tea at {'{'}tea_time{'}'}"). They do not auto-schedule check-ins.</p>

        <div className="pt-2">
          <label className="text-sm font-medium text-ayana-text">Health / routine notes</label>
          <textarea
            value={form.notes || ""}
            onChange={(e) => setForm({ ...form, notes: e.target.value.slice(0, 300) })}
            data-testid={t("notes")}
            placeholder="e.g. Uses a walking stick, hard of hearing in left ear."
            rows={3}
            className={`mt-1.5 ${inputCls} resize-none text-sm`}
          />
          <p className="text-xs text-ayana-muted mt-1 text-right">{(form.notes || "").length}/300</p>
        </div>

        {/* Quiet hours / DND guard */}
        <div className="pt-4 border-t border-ayana-line/50">
          <label className="text-sm font-medium text-ayana-text flex items-center gap-1.5">
            <VolumeX className="w-3.5 h-3.5 text-ayana-primary" /> Quiet hours (no messages sent)
          </label>
          <p className="text-xs text-ayana-muted mt-1">Prevents check-ins from firing during sleep, prayer, etc. Leave off to let AYANA learn this automatically from reply patterns.</p>
          <div className="flex items-center gap-2 mt-3">
            <button
              type="button"
              onClick={() => setForm({ ...form, auto_activity_detection: !form.auto_activity_detection })}
              data-testid={t("auto-activity-toggle")}
              className={`px-3.5 py-1.5 rounded-full text-xs font-medium border transition-colors ${
                form.auto_activity_detection
                  ? "bg-ayana-primary text-white border-ayana-primary"
                  : "bg-white text-ayana-secondary border-ayana-line hover:bg-ayana-alt"
              }`}
            >
              {form.auto_activity_detection ? "Auto-detect: On" : "Auto-detect: Off"}
            </button>
          </div>
          {!form.auto_activity_detection && (
            <div className="grid grid-cols-2 gap-3 mt-3 max-w-sm">
              <div>
                <label className="text-[10px] uppercase font-bold text-ayana-muted ml-1">Quiet from</label>
                <input type="time" value={form.activity_window_start || ""} onChange={(e) => setForm({ ...form, activity_window_start: e.target.value })} data-testid={t("dnd-start")} className={smInputCls} />
              </div>
              <div>
                <label className="text-[10px] uppercase font-bold text-ayana-muted ml-1">Quiet until</label>
                <input type="time" value={form.activity_window_end || ""} onChange={(e) => setForm({ ...form, activity_window_end: e.target.value })} data-testid={t("dnd-end")} className={smInputCls} />
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── Section 4: Medicines (optional) ── */}
      <section className="space-y-5">
        <div className="flex items-center justify-between pb-2 border-b border-ayana-line/50">
          <div className="flex items-center gap-2">
            <Pill className="w-4.5 h-4.5 text-ayana-primary" />
            <h4 className="font-display font-medium text-ayana-text">4. Medicine reminders</h4>
            <span className="text-[10px] uppercase font-bold tracking-wide text-ayana-muted bg-ayana-alt px-2 py-0.5 rounded-full">Optional</span>
          </div>
          <span className="text-xs text-ayana-muted">{(form.medicine_list || []).length + (form.messages || []).filter((m) => (m.type || "checkin") === "reminder").length}/{maxReminders} · {plan?.name}</span>
        </div>
        <p className="text-xs text-ayana-secondary">Add medicines your parent takes daily. AYANA will send a WhatsApp reminder at the time you set for each medicine.</p>

        {(form.medicine_list || []).length > 0 && (
          <div className="space-y-2">
            {form.medicine_list.map((m, idx) => (
              <div key={idx} className="flex items-center justify-between rounded-xl border border-ayana-line px-4 py-3 bg-warm-cream/20">
                <div className="flex items-center gap-3">
                  <span className="text-xl" style={{ color: COLOR_HEX[m.color] || COLOR_HEX.white }}>{SHAPE_ICON[m.shape] || "💊"}</span>
                  <div>
                    <p className="text-sm font-medium text-ayana-text">{m.name} {m.dose && `· ${m.dose}`}</p>
                    <p className="text-xs text-ayana-secondary">{m.reminder_time || "—"} · {(m.timing || "").replace("_", " ")}</p>
                    {m.notes && <p className="text-xs text-ayana-muted italic mt-0.5">{m.notes}</p>}
                  </div>
                </div>
                <button onClick={() => removeMedicine(idx)} data-testid={t(`med-remove-${idx}`)} className="text-ayana-muted hover:text-red-500"><Trash2 className="w-4 h-4" /></button>
              </div>
            ))}
          </div>
        )}

        {(form.medicine_list || []).length + (form.messages || []).filter((m) => (m.type || "checkin") === "reminder").length < maxReminders ? (
          <div className="bg-warm-cream/30 rounded-xl p-4 border border-ayana-line/50 space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <input value={newMed.name} onChange={(e) => setNewMed({ ...newMed, name: e.target.value })} placeholder="Medicine name" data-testid={t("med-name")} className={smInputCls} />
              <input value={newMed.dose} onChange={(e) => setNewMed({ ...newMed, dose: e.target.value })} placeholder="Dose (e.g. 1 tab)" data-testid={t("med-dose")} className={smInputCls} />
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <div>
                <label className="text-[10px] uppercase font-bold text-ayana-muted ml-1">Remind at</label>
                <input type="time" value={newMed.reminder_time} onChange={(e) => setNewMed({ ...newMed, reminder_time: e.target.value })} data-testid={t("med-time")} className={smInputCls} />
              </div>
              <div>
                <label className="text-[10px] uppercase font-bold text-ayana-muted ml-1">Shape</label>
                <select value={newMed.shape} onChange={(e) => setNewMed({ ...newMed, shape: e.target.value })} data-testid={t("med-shape")} className={smInputCls}>
                  {shapes.map((s) => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] uppercase font-bold text-ayana-muted ml-1">Color</label>
                <select value={newMed.color} onChange={(e) => setNewMed({ ...newMed, color: e.target.value })} data-testid={t("med-color")} className={smInputCls}>
                  {colors.map((c) => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] uppercase font-bold text-ayana-muted ml-1">Timing</label>
                <select value={newMed.timing} onChange={(e) => setNewMed({ ...newMed, timing: e.target.value })} data-testid={t("med-timing")} className={smInputCls}>
                  {timings.map((tm) => <option key={tm} value={tm}>{tm.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="text-[10px] uppercase font-bold text-ayana-muted ml-1">Notes (optional, for your reference — not sent to your parent)</label>
              <input
                value={newMed.notes || ""}
                onChange={(e) => setNewMed({ ...newMed, notes: e.target.value.slice(0, 200) })}
                placeholder="e.g. Take with warm water"
                data-testid={t("med-notes")}
                className={smInputCls}
              />
            </div>
            <button onClick={addMedicine} data-testid={t("med-add")} className="inline-flex items-center gap-1.5 text-sm text-ayana-primary font-medium hover:text-ayana-primary-hover transition-colors">
              <Plus className="w-4 h-4" /> Add medicine
            </button>
          </div>
        ) : (
          <p className="text-xs text-ayana-muted text-center py-2">
            Maximum {maxReminders} reminders (medicines + health reminders combined) for {plan?.name}. Upgrade your plan for more.
          </p>
        )}
      </section>
    </div>
  );
}