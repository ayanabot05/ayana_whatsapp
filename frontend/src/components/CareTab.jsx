/**
 * CareTab.jsx — Dashboard "Care" tab.
 *  • Emergency Contacts: add/edit the phone numbers alerted on emergencies
 *    or when a parent goes quiet (distinct from the Care Circle).
 *  • Send a Moment: push a warm note / photo that Ayana delivers to the parent.
 *  • Emergency Events: history of alerts sent to emergency contacts.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Phone, Plus, Trash2, Send, Heart, ImagePlus, Loader2, ShieldAlert, Activity, Lock, AlertTriangle, Bell, Clock, X } from "lucide-react";
import { api, formatApiError } from "@/lib/api";
import { PhoneInput } from "@/components/PhoneInput";
import { EmptyState } from "@/components/ui/EmptyState";
import { toast } from "sonner";

const inputCls = "w-full px-3.5 py-2.5 rounded-lg border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-accent/50 focus:border-ayana-accent transition";

function EmergencyEventsHistory({ parent }) {
  const qc = useQueryClient();
  const { data: events, isLoading } = useQuery({
    queryKey: ["emergency-events", parent.id],
    queryFn: () => api.get(`/parents/${parent.id}/emergency-events`).then((r) => r.data || []),
  });

  const resolve = async (id, status) => {
    try {
      await api.put(`/emergency-events/${id}`, { status });
      toast.success(`Event marked as ${status}.`);
      qc.invalidateQueries({ queryKey: ["emergency-events", parent.id] });
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (isLoading) return null;
  if (!events || events.length === 0) return null;

  return (
    <div className="rounded-2xl border border-red-200 bg-red-50/30 p-5 mt-4" data-testid={`emergency-events-${parent.id}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-red-100">
          <Bell className="w-4 h-4 text-red-600" />
        </span>
        <h3 className="font-display text-lg font-semibold text-ayana-text">Emergency & alert history: {parent.name}</h3>
      </div>
      <p className="text-sm text-ayana-muted mb-4">Past keywords detected or distress alerts sent to emergency contacts.</p>

      <div className="space-y-3">
        {events.map((ev) => (
          <div key={ev.id || ev._id} className="bg-white rounded-xl border border-red-200 p-4 text-sm" data-testid={`emergency-event-${ev.id || ev._id}`}>
            <div className="flex items-center justify-between flex-wrap gap-2 mb-1">
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-0.5 rounded-full bg-red-100 text-red-700">
                <AlertTriangle className="w-3 h-3" /> {(ev.keywords || []).join(", ") || "Emergency flagged"}
              </span>
              <span className="text-xs text-ayana-muted flex items-center gap-1">
                <Clock className="w-3 h-3" /> {new Date(ev.created_at).toLocaleString()}
              </span>
            </div>
            {ev.body && <p className="text-ayana-text font-medium mt-1">&ldquo;{ev.body}&rdquo;</p>}
            <div className="flex items-center justify-between mt-3 gap-2">
              <p className="text-xs text-ayana-secondary">Status: <span className="font-medium capitalize">{ev.status || "open"}</span></p>
              {ev.status === "open" && (
                <div className="flex gap-2">
                  <button onClick={() => resolve(ev.id || ev._id, "resolved")} className="px-3 py-1 bg-ayana-primary text-white text-xs font-medium rounded-full hover:bg-ayana-primary-hover">Resolve</button>
                  <button onClick={() => resolve(ev.id || ev._id, "false_positive")} className="px-3 py-1 border border-red-300 text-red-600 text-xs font-medium rounded-full hover:bg-red-50">False positive</button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmergencyContacts({ parent }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["emergency", parent.id],
    queryFn: () => api.get(`/parents/${parent.id}/emergency-contacts`).then((r) => r.data.contacts || []),
  });
  const [rows, setRows] = useState(null);
  const [saving, setSaving] = useState(false);
  const contacts = rows ?? data ?? [];

  const update = (i, key, val) => {
    const next = contacts.map((c, idx) => (idx === i ? { ...c, [key]: val } : c));
    setRows(next);
  };
  const add = () => setRows([...(contacts || []), { name: "", phone: "+91", relation: "" }]);
  const remove = (i) => setRows(contacts.filter((_, idx) => idx !== i));

  const save = async () => {
    setSaving(true);
    try {
      const clean = contacts.filter((c) => c.name && c.phone && c.phone.length > 5);
      await api.put(`/parents/${parent.id}/emergency-contacts`, { contacts: clean });
      toast.success("Emergency contacts saved.");
      setRows(null);
      qc.invalidateQueries({ queryKey: ["emergency", parent.id] });
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-2xl border border-ayana-line bg-white p-5" data-testid={`emergency-card-${parent.id}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "rgba(232,89,12,0.12)" }}>
          <ShieldAlert className="w-4 h-4 text-ayana-accent" />
        </span>
        <h3 className="font-display text-lg font-semibold text-ayana-text">Emergency contacts: {parent.name}</h3>
      </div>
      <p className="text-sm text-ayana-muted mb-4">Alerted immediately on an emergency, or if {parent.name} doesn&apos;t reply all day. Up to 5.</p>

      {isLoading ? (
        <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-ayana-muted" /></div>
      ) : (
        <div className="space-y-3">
          {contacts.length === 0 && <p className="text-sm text-ayana-muted">No emergency contacts yet.</p>}
          {contacts.map((c, i) => (
            <div key={i} className="grid sm:grid-cols-[1fr_1fr_auto] gap-2 items-start" data-testid={`emergency-row-${parent.id}-${i}`}>
              <input value={c.name} onChange={(e) => update(i, "name", e.target.value)} placeholder="Name (e.g. Ravi)" className={inputCls} data-testid={`emergency-name-${i}`} />
              <PhoneInput value={c.phone} onChange={(v) => update(i, "phone", v)} testid={`emergency-phone-${i}`} />
              <div className="flex gap-2">
                <input value={c.relation || ""} onChange={(e) => update(i, "relation", e.target.value)} placeholder="Relation" className={`${inputCls} sm:w-28`} data-testid={`emergency-relation-${i}`} />
                <button onClick={() => remove(i)} className="shrink-0 w-10 h-10 rounded-lg border border-ayana-line text-ayana-muted hover:text-ayana-accent hover:border-ayana-accent/50 flex items-center justify-center" data-testid={`emergency-remove-${i}`}>
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
          <div className="flex items-center justify-between pt-1">
            <button onClick={add} disabled={contacts.length >= 5} className="inline-flex items-center gap-1.5 text-sm font-medium text-ayana-primary hover:text-ayana-primary-hover disabled:opacity-40" data-testid={`emergency-add-${parent.id}`}>
              <Plus className="w-4 h-4" /> Add contact
            </button>
            <button onClick={save} disabled={saving} className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50" data-testid={`emergency-save-${parent.id}`}>
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Phone className="w-4 h-4" />} Save contacts
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const optimizeImage = (file) => {
  return new Promise((resolve) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const canvas = document.createElement("canvas");
      const MAX_DIMENSION = 1200;
      let { width, height } = img;
      if (width > height && width > MAX_DIMENSION) {
        height = (height * MAX_DIMENSION) / width;
        width = MAX_DIMENSION;
      } else if (height > MAX_DIMENSION) {
        width = (width * MAX_DIMENSION) / height;
        height = MAX_DIMENSION;
      }
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0, width, height);
      const optimized = canvas.toDataURL("image/jpeg", 0.8);
      URL.revokeObjectURL(url);
      resolve(optimized);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve(null);
    };
    img.src = url;
  });
};

function MomentComposer({ parents, moments, quota, onMomentSent }) {
  const [parentId, setParentId] = useState(parents[0]?.id || "");
  const [text, setText] = useState("");
  const [imageUrls, setImageUrls] = useState([]);
  const [sending, setSending] = useState(false);

  const MAX_IMAGES = 2;

  const remaining = quota?.remaining;
  const limit = quota?.limit ?? 2;
  const outOfMoments = remaining === 0;

  const handleImageSelect = async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    if (imageUrls.length + files.length > MAX_IMAGES) {
      toast.error(`You can attach up to ${MAX_IMAGES} images.`);
      return;
    }
    const newUrls = [];
    for (const f of files) {
      if (!f.type.startsWith("image/")) {
        toast.error("Only image files are allowed.");
        return;
      }
      if (f.size > 5 * 1024 * 1024) {
        toast.error("Each image must be under 5 MB.");
        return;
      }
      const optimized = await optimizeImage(f);
      if (optimized) newUrls.push(optimized);
    }
    setImageUrls([...imageUrls, ...newUrls].slice(0, MAX_IMAGES));
  };

  const removeImage = (idx) => {
    setImageUrls(imageUrls.filter((_, i) => i !== idx));
  };

  const send = async () => {
    if (!parentId || !text.trim()) { toast.error("Pick a parent and write a message."); return; }
    setSending(true);
    try {
      const uploadedUrls = [];
      for (const base64 of imageUrls) {
        const form = new FormData();
        const response = await fetch(base64);
        const blob = await response.blob();
        form.append("file", blob, "image.jpg");
        const { data } = await api.post("/moments/upload-image", form, {
          headers: { "Content-Type": "multipart/form-data" }
        });
        if (data.url) uploadedUrls.push(data.url);
      }
      await api.post("/moments", {
        parent_id: parentId,
        text: text.trim(),
        image_urls: uploadedUrls,
      });
      toast.success("Sent 💛 Ayana is delivering it now.");
      setText("");
      setImageUrls([]);
      onMomentSent?.();
    } catch (e) {
      if (e.response?.status === 501) {
        toast.error("Photo sharing isn't switched on yet — your text moment can still be sent without the photo.", { duration: 8000 });
      } else {
        toast.error(formatApiError(e.response?.data?.detail));
      }
    } finally {
      setSending(false);
    }
  };

  const parentName = (id) => parents.find((p) => p.id === id)?.name || "Parent";

  return (
    <div className="rounded-2xl border border-ayana-line bg-white p-5" data-testid="moment-composer">
      <div className="flex items-center gap-2 mb-1">
        <span className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "rgba(212,150,10,0.14)" }}>
          <Heart className="w-4 h-4 text-ayana-gold" />
        </span>
        <h3 className="font-display text-lg font-semibold text-ayana-text">Send a moment</h3>
      </div>
      <p className="text-sm text-ayana-muted mb-4">A warm note + photos (up to 2). Ayana delivers it to their WhatsApp with love.</p>

      {typeof remaining === "number" && (
        <div className="mb-4 flex items-center gap-2 text-xs" data-testid="moment-quota">
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-medium ${outOfMoments ? "bg-red-50 text-red-600" : "bg-ayana-gold/15 text-ayana-gold"}`}>
            <Heart className="w-3 h-3" /> {remaining} of {limit} special moments left this month
          </span>
          {outOfMoments && <span className="text-ayana-muted">Resets on the 1st.</span>}
        </div>
      )}

      <div className="space-y-3">
        <select value={parentId} onChange={(e) => setParentId(e.target.value)} className={inputCls} data-testid="moment-parent">
          {parents.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <textarea value={text} onChange={(e) => setText(e.target.value.slice(0, 600))} rows={3} placeholder="Thinking of you, Amma. Had a great day and wanted to say I love you ❤️" className={`${inputCls} resize-none`} data-testid="moment-text" />
        <div className="flex items-start gap-2">
          <ImagePlus className="w-5 h-5 text-ayana-muted shrink-0 mt-0.5" />
          <div className="flex-1">
            <label className="border border-ayana-line border-dashed rounded-lg p-3 block text-center cursor-pointer hover:bg-ayana-alt transition">
              <span className="text-sm text-ayana-muted">Click to add photo or drag & drop</span>
              <input
                type="file"
                accept="image/*"
                multiple
                onChange={handleImageSelect}
                className="hidden"
                data-testid="moment-file-input"
              />
            </label>
            {imageUrls.length >= MAX_IMAGES && (
              <p className="text-xs text-ayana-muted mt-1.5">Maximum {MAX_IMAGES} photos.</p>
            )}
          </div>
        </div>
        {imageUrls.length > 0 && (
          <div className="flex flex-wrap gap-2" data-testid="moment-image-previews">
            {imageUrls.map((url, idx) => (
              <div key={idx} className="relative w-16 h-16 rounded-lg overflow-hidden border border-ayana-line">
                <img src={url} alt={`preview-${idx}`} className="w-full h-full object-cover" />
                <button
                  onClick={() => removeImage(idx)}
                  className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-red-100 text-red-600 flex items-center justify-center"
                  data-testid={`moment-image-remove-${idx}`}
                >
                  <X className="w-2.5 h-2.5" />
                </button>
              </div>
            ))}
          </div>
        )}
        <div className="flex justify-end">
          <button onClick={send} disabled={sending || !text.trim() || outOfMoments} className="btn-saffron inline-flex items-center gap-2 px-6 py-2.5 rounded-full text-sm font-semibold disabled:opacity-50" data-testid="moment-send">
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />} {outOfMoments ? "Limit reached" : "Send"}
          </button>
        </div>
      </div>

      {moments && moments.length > 0 && (
        <div className="mt-6 border-t border-ayana-line pt-4">
          <p className="text-xs font-semibold text-ayana-muted uppercase tracking-wide mb-3">Recently sent</p>
          <div className="space-y-3" data-testid="moments-list">
            {moments.slice(0, 5).map((m) => (
              <div key={m.id} className="flex items-start gap-3 text-sm">
                <Heart className="w-3.5 h-3.5 text-ayana-gold mt-1 shrink-0" />
                <div>
                  <p className="text-ayana-text">{m.text}</p>
                  {(m.image_urls || m.image_url) && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {(m.image_urls || (m.image_url ? [m.image_url] : [])).map((img, i) => (
                        <img key={i} src={img} alt="sent" className="w-16 h-16 object-cover rounded-lg border border-ayana-line" />
                      ))}
                    </div>
                  )}
                  <p className="text-ayana-muted">to {parentName(m.parent_id)}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function RecoveryCard({ parents, schedules, planId, limits }) {
  const qc = useQueryClient();
  const parentName = (id) => parents.find((p) => p.id === id)?.name || "Parent";
  const [days, setDays] = useState(30);
  const [reminders, setReminders] = useState([{ time: "12:00", category: "medicine" }]);
  const [busy, setBusy] = useState("");

  const isRaksha = limits?.recovery_mode ?? planId === "raksha";
  const maxExtra = limits?.recovery_extra_reminders ?? 2;

  const addReminder = () => {
    if (reminders.length < maxExtra) {
      setReminders([...reminders, { time: "12:00", category: "medicine" }]);
    }
  };
  const removeReminder = (idx) => setReminders(reminders.filter((_, i) => i !== idx));
  const updateReminder = (idx, val) => setReminders(reminders.map((r, i) => i === idx ? { ...r, time: val } : r));

  const start = async (sched) => {
    setBusy(sched.id);
    try {
      await api.post(`/schedules/${sched.id}/recovery/start`, {
        days: Number(days) || 30,
        extra_reminders: reminders,
      });
      toast.success("Recovery mode started 💛");
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["schedules"] });
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); } finally { setBusy(""); }
  };
  const end = async (sched) => {
    setBusy(sched.id);
    try {
      await api.post(`/schedules/${sched.id}/recovery/end`);
      toast.success("Recovery mode ended.");
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["schedules"] });
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); } finally { setBusy(""); }
  };

  return (
    <div className="rounded-2xl border border-ayana-line bg-white p-5" data-testid="recovery-card">
      <div className="flex items-center gap-2 mb-1">
        <span className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "rgba(10,89,64,0.12)" }}>
          <Activity className="w-4 h-4 text-ayana-primary" />
        </span>
        <h3 className="font-display text-lg font-semibold text-ayana-text">Recovery mode</h3>
        {!isRaksha && <span className="ml-1 inline-flex items-center gap-1 text-xs text-ayana-gold"><Lock className="w-3 h-3" /> Raksha</span>}
      </div>
      <p className="text-sm text-ayana-muted mb-4">After surgery or illness, add extra medicine reminders for a set period. Ayana ends it automatically.</p>

      {!isRaksha ? (
        <p className="text-sm text-ayana-secondary">Upgrade to <strong>Raksha</strong> to enable recovery mode.</p>
      ) : schedules.length === 0 ? (
        <p className="text-sm text-ayana-muted">Create a schedule first.</p>
      ) : (
        <div className="space-y-4">
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-ayana-muted uppercase tracking-wider">Extra Reminders</label>
              <button onClick={addReminder} disabled={reminders.length >= maxExtra} className="text-xs text-ayana-primary font-medium hover:underline disabled:opacity-40">
                + Add reminder ({reminders.length}/{maxExtra})
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {reminders.map((r, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input type="time" value={r.time} onChange={(e) => updateReminder(i, e.target.value)} className={inputCls} data-testid={`recovery-time-${i}`} />
                  {reminders.length > 1 && (
                    <button onClick={() => removeReminder(i)} className="p-2 text-ayana-muted hover:text-ayana-accent">
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold text-ayana-muted uppercase tracking-wider">Duration (days)</label>
            <input type="number" min={1} max={90} value={days} onChange={(e) => setDays(e.target.value)} className={`mt-1 ${inputCls} w-24`} data-testid="recovery-days" />
          </div>
          {schedules.map((s) => (
            <div key={s.id} className="flex items-center justify-between rounded-lg border border-ayana-line px-4 py-3" data-testid={`recovery-sched-${s.id}`}>
              <div className="text-sm">
                <span className="font-medium text-ayana-text">{parentName(s.parent_id)}</span>
                {s.recovery_mode
                  ? <span className="ml-2 text-ayana-primary">● Active{s.recovery_until ? ` until ${s.recovery_until}` : ""}</span>
                  : <span className="ml-2 text-ayana-muted">Off</span>}
              </div>
              {s.recovery_mode ? (
                <button onClick={() => end(s)} disabled={busy === s.id} className="px-4 py-2 rounded-full border border-ayana-line text-sm font-medium text-ayana-accent hover:border-ayana-accent/50 disabled:opacity-50" data-testid={`recovery-end-${s.id}`}>
                  {busy === s.id ? <Loader2 className="w-4 h-4 animate-spin" /> : "End early"}
                </button>
              ) : (
                <button onClick={() => start(s)} disabled={busy === s.id} className="px-4 py-2 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50" data-testid={`recovery-start-${s.id}`}>
                  {busy === s.id ? <Loader2 className="w-4 h-4 animate-spin" /> : "Start recovery"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function CareTab({ parents, schedules = [], planId, limits, moments, quota, onMomentSent }) {
  if (!parents || parents.length === 0) {
    return <EmptyState text="Add a parent first to manage moments and emergency contacts." />;
  }
  return (
    <div className="space-y-6" data-testid="care-tab">
      <MomentComposer parents={parents} moments={moments} quota={quota} onMomentSent={onMomentSent} />
      <RecoveryCard parents={parents} schedules={schedules} planId={planId} limits={limits} />
      {parents.map((p) => (
        <div key={p.id} className="space-y-4">
          <EmergencyContacts parent={p} />
          <EmergencyEventsHistory parent={p} />
        </div>
      ))}
    </div>
  );
}

export default CareTab;