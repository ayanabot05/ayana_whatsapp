
import {
  Sunrise, Coffee, Heart, Utensils, Sun, Moon, Star, Pill, Droplet,
  Activity, HeartPulse, Candy, MessageCircle, Plus, Trash2,
} from "lucide-react";
import { toast } from "sonner";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

export const CATEGORY_ICONS = {
  sunrise: Sunrise, coffee: Coffee, heart: Heart, utensils: Utensils, sun: Sun,
  moon: Moon, star: Star, pill: Pill, droplet: Droplet, activity: Activity,
  "heart-pulse": HeartPulse, candy: Candy,
};

const CATEGORY_LABELS = {
  morning_wish: "Morning Wish",
  breakfast: "Breakfast Check",
  lunch: "Lunch Check",
  dinner: "Dinner Check",
  afternoon_checkin: "Afternoon Check-in",
  tea_check: "Tea / Coffee Check",
  walk_check: "Walk Check",
  how_feeling: "How Are You Feeling?",
  goodnight: "Good Night",
  love_note: "Love Note",
  medicine: "Medicine Reminder",
  water: "Water Check",
  bp_check: "BP Check",
  sugar_check: "Sugar Check",
  health_check: "Health Check",
};

const CATEGORY_ICON_MAP = {
  morning_wish: "sunrise",
  breakfast: "coffee",
  lunch: "utensils",
  dinner: "utensils",
  afternoon_checkin: "sun",
  tea_check: "coffee",
  walk_check: "heart",
  how_feeling: "heart",
  goodnight: "moon",
  love_note: "star",
  medicine: "pill",
  water: "droplet",
  bp_check: "activity",
  sugar_check: "candy",
  health_check: "heart-pulse",
};

const CATEGORY_BUTTONS = {
  morning_wish: ["Slept well 😴", "So-so 🙂", "Couldn't sleep 😔"],
  how_feeling: ["Good 😊", "Okay 🙂", "Not well 😟"],
  goodnight: ["Good day 😊", "Average 🙂", "Tired 😟"],
  love_note: ["Love you too ❤", "Thanks 🙏", "Missing you"],
  medicine: ["Done ✅", "Not yet", "Skipped"],
  water: ["Done 💧", "Will now", "Forgot"],
  bp_check: ["Checked ✅", "Not yet", "No machine"],
  sugar_check: ["Checked ✅", "Not yet", "No machine"],
  health_check: ["All good 🩺", "Some pain", "Bad day 😟"],
  breakfast: ["Had it 🍵", "Having now", "Not hungry"],
  lunch: ["Had it 🍽", "Not yet", "Not hungry"],
  dinner: ["Done 🌙", "Not yet", "Skipping"],
  afternoon_checkin: ["Resting 🛌", "Busy", "Not well 😟"],
  tea_check: ["Done ☕", "Now", "Skipped"],
  walk_check: ["Done 🚶♀", "Later", "Not today"],
};

export function normalizeCategory(c) {
  const key = c.key || c.value || c;
  return {
    key,
    label: c.label || CATEGORY_LABELS[key] || key.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase()),
    type: c.type || "checkin",
    icon: c.icon || CATEGORY_ICON_MAP[key] || "heart",
  };
}

function useFilteredRows(messages, setMessages, matchType) {
  const indices = messages
    .map((m, i) => i)
    .filter((i) => (messages[i].type || "checkin") === matchType);
  const updateAt = (realIdx, key, val) => {
    const next = [...messages];
    next[realIdx] = { ...next[realIdx], [key]: val };
    setMessages(next);
  };
  const removeAt = (realIdx) => setMessages(messages.filter((_, i) => i !== realIdx));
  return { indices, updateAt, removeAt };
}

function CategoryRow({ m, realIdx, cats, catByKey, updateAt, removeAt, testPrefix }) {
  const cat = catByKey[m.category] || normalizeCategory({ key: m.category, type: m.type || "checkin" });
  const Icon = CATEGORY_ICONS[cat.icon] || MessageCircle;
  const buttons = CATEGORY_BUTTONS[m.category] || [];
  return (
    <div className="bg-white rounded-xl border border-ayana-line p-2.5" data-testid={`${testPrefix}-row-${realIdx}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-9 h-9 rounded-lg bg-ayana-primary/8 flex items-center justify-center shrink-0"><Icon className="w-4.5 h-4.5 text-ayana-primary" strokeWidth={1.5} /></span>
        <input type="time" value={m.time} onChange={(e) => updateAt(realIdx, "time", e.target.value)} data-testid={`${testPrefix}-time-${realIdx}`}
          className="px-3 py-2 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-accent/50 w-[8.5rem]" />
        <Select value={m.category} onValueChange={(v) => updateAt(realIdx, "category", v)}>
          <SelectTrigger className="flex-1 min-w-[9rem] bg-white" data-testid={`${testPrefix}-cat-${realIdx}`}><SelectValue /></SelectTrigger>
          <SelectContent className="max-h-64">
            {cats.map((c) => {
              const CI = CATEGORY_ICONS[c.icon] || MessageCircle;
              return <SelectItem key={c.key} value={c.key}><span className="flex items-center gap-2"><CI className="w-4 h-4 text-ayana-primary" /> {c.label}</span></SelectItem>;
            })}
          </SelectContent>
        </Select>
        <button onClick={() => removeAt(realIdx)} data-testid={`${testPrefix}-remove-${realIdx}`} className="text-ayana-muted hover:text-red-500 transition-colors p-2 shrink-0"><Trash2 className="w-4 h-4" /></button>
      </div>
      {buttons.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 mt-2 pl-11" data-testid={`${testPrefix}-buttons-${realIdx}`}>
          <span className="text-[11px] text-ayana-muted mr-0.5">They'll tap:</span>
          {buttons.map((b, i) => (
            <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-ayana-primary/8 text-ayana-primary border border-ayana-primary/15">{b}</span>
          ))}
        </div>
      )}
    </div>
  );
}

export function ScheduleEditor({ messages, setMessages, categories, maxCheckins }) {
  const cats = categories.map(normalizeCategory).filter((c) => c.type === "checkin");
  const catByKey = Object.fromEntries(cats.map((c) => [c.key, c]));
  const { indices, updateAt, removeAt } = useFilteredRows(messages, setMessages, "checkin");

  if (!cats.length) {
    return (
      <div className="py-6 text-center text-sm text-ayana-muted animate-pulse">
        Loading schedule categories…
      </div>
    );
  }

  const add = () => {
    if (indices.length >= maxCheckins) {
      toast.error(`Your plan allows up to ${maxCheckins} daily check-ins. Upgrade for more.`);
      return;
    }
    const first = cats[0]?.key || "morning_wish";
    setMessages([...messages, { time: "09:00", category: first, type: "checkin" }]);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2" data-testid="checkins-list">
        {indices.map((realIdx) => (
          <CategoryRow key={realIdx} m={messages[realIdx]} realIdx={realIdx} cats={cats} catByKey={catByKey} updateAt={updateAt} removeAt={removeAt} testPrefix="sched" />
        ))}
      </div>
      {indices.length === 0 && (
        <p className="text-sm text-ayana-muted text-center py-3">No check-ins yet. Add your first one below.</p>
      )}
      <button onClick={add} data-testid="add-checkin" disabled={indices.length >= maxCheckins}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ayana-accent hover:text-ayana-accent-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
        <Plus className="w-4 h-4" /> Add check-in
      </button>
    </div>
  );
}

// Health reminders — WATER / BP / SUGAR / HEALTH CHECK ONLY
// Medicine is NOT manually addable here — it comes from medicine_list auto-sync
export function ReminderEditor({ messages, setMessages, categories, maxReminders, medicineCount = 0 }) {
  const HEALTH_KEYS = ["water", "health_check", "bp_check", "sugar_check"];
  const allCats = categories.map(normalizeCategory);
  // Only show the 4 health keys, explicitly exclude 'medicine'
  const cats = allCats.filter((c) => HEALTH_KEYS.includes(c.key));

  const catByKey = Object.fromEntries(cats.map((c) => [c.key, c]));
  const { indices, updateAt, removeAt } = useFilteredRows(messages, setMessages, "reminder");
  const totalUsed = indices.length + medicineCount;

  if (!cats.length) {
    return null;
  }

  const add = () => {
    if (totalUsed >= maxReminders) {
      toast.error(`Your plan allows up to ${maxReminders} reminders total (medicines + health reminders). Upgrade for more.`);
      return;
    }
    const first = cats[0]?.key || "water";
    setMessages([...messages, { time: "09:00", category: first, type: "reminder" }]);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2" data-testid="reminders-list">
        {indices.map((realIdx) => (
          <CategoryRow key={realIdx} m={messages[realIdx]} realIdx={realIdx} cats={cats} catByKey={catByKey} updateAt={updateAt} removeAt={removeAt} testPrefix="reminder" />
        ))}
      </div>
      {indices.length === 0 && (
        <p className="text-sm text-ayana-muted text-center py-3">No health reminders yet.</p>
      )}
      <button onClick={add} data-testid="add-reminder" disabled={totalUsed >= maxReminders}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ayana-accent hover:text-ayana-accent-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
        <Plus className="w-4 h-4" /> Add reminder
      </button>
    </div>
  );
}

export function ActivityEditor({ messages, setMessages, categories, maxActivities }) {
  const cats = categories.map(normalizeCategory).filter((c) => c.type === "activity");
  const catByKey = Object.fromEntries(cats.map((c) => [c.key, c]));
  const { indices, updateAt, removeAt } = useFilteredRows(messages, setMessages, "activity");

  if (!cats.length) {
    return null;
  }

  const add = () => {
    if (indices.length >= maxActivities) {
      toast.error(`Your plan allows up to ${maxActivities} daily activit${maxActivities === 1 ? "y" : "ies"}. Upgrade for more.`);
      return;
    }
    const first = cats[0]?.key || "walk_check";
    setMessages([...messages, { time: "17:00", category: first, type: "activity" }]);
  };

  return (
    <div className="space-y-3">
      <div className="space-y-2" data-testid="activities-list">
        {indices.map((realIdx) => (
          <CategoryRow key={realIdx} m={messages[realIdx]} realIdx={realIdx} cats={cats} catByKey={catByKey} updateAt={updateAt} removeAt={removeAt} testPrefix="activity" />
        ))}
      </div>
      {indices.length === 0 && (
        <p className="text-sm text-ayana-muted text-center py-3">No daily activities yet — try a walk, tea or water nudge.</p>
      )}
      <button onClick={add} data-testid="add-activity" disabled={indices.length >= maxActivities}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-ayana-accent hover:text-ayana-accent-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
        <Plus className="w-4 h-4" /> Add activity
      </button>
    </div>
  );
}

