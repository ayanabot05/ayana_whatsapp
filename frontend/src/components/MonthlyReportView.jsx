
import { useMemo, useState, useEffect } from "react";
import {
  BarChart3,
  CheckCircle2,
  Clock,
  MessageCircle,
  Smile,
  Pill,
  AlertCircle,
  Download,
  Loader2,
  Calendar,
  User,
  Send
} from "lucide-react";
import { toast } from "sonner";

function groupByCategory(days) {
  const map = {};
  days.forEach((d) => {
    (d.messages || []).forEach((m) => {
      if (!map[m.category]) map[m.category] = { sent: 0, completed: 0, label: m.category };
      map[m.category].sent += 1;
      if (m.replied || m.reply_status === "done") map[m.category].completed += 1;
    });
  });
  return Object.values(map);
}

const todayIso = () => new Date().toISOString().slice(0, 10);

export function MonthlyReportView({ parents, plan, user, checkinsData }) {
  const parentOptions = useMemo(() => {
    return (checkinsData?.parents || []).map((p) => ({
      id: p.parent_id,
      name: p.name || "Parent",
    }));
  }, [checkinsData]);

  const [selectedParentId, setSelectedParentId] = useState(() => parentOptions[0]?.id || "");
  const [selectedMonth, setSelectedMonth] = useState(() => todayIso().slice(0, 7));

  // Keep parent valid when data loads
  useEffect(() => {
    if (parentOptions.length && !parentOptions.find((p) => p.id === selectedParentId)) {
      setSelectedParentId(parentOptions[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [parentOptions]);

  const selectedParent = useMemo(() => {
    return (checkinsData?.parents || []).find((p) => p.parent_id === selectedParentId);
  }, [checkinsData, selectedParentId]);

  // Months for SELECTED parent only
  const monthOptions = useMemo(() => {
    const set = new Set();
    const today = todayIso();
    const days = selectedParent?.days || [];
    days.forEach((d) => {
      const iso = d.day_key === "today" ? today : d.day_key;
      if (iso && iso.length >= 7) set.add(iso.slice(0, 7));
    });
    set.add(today.slice(0, 7));
    return Array.from(set).sort().reverse();
  }, [selectedParent]);

  useEffect(() => {
    if (monthOptions.length && !monthOptions.includes(selectedMonth)) {
      setSelectedMonth(monthOptions[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monthOptions]);

  const monthLabel = useMemo(() => {
    const [y, m] = selectedMonth.split("-").map(Number);
    if (!y || !m) return selectedMonth;
    return new Date(y, m - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
  }, [selectedMonth]);

  const allDays = useMemo(() => {
    if (!selectedParent) return [];
    const today = todayIso();
    return (selectedParent.days || [])
      .map((d) => ({
        ...d,
        _iso: d.day_key === "today" ? today : d.day_key,
      }))
      .filter((d) => d._iso && d._iso.slice(0, 7) === selectedMonth);
  }, [selectedParent, selectedMonth]);

  const allMessages = useMemo(() => allDays.flatMap((d) => d.messages || []), [allDays]);

  const stats = useMemo(() => {
    const totalSent = allMessages.length;
    const totalCompleted = allMessages.filter((m) => m.replied || m.reply_status === "done").length;
    const totalSkipped = allMessages.filter((m) => m.reply_status === "skipped").length;
    const voiceNotes = allMessages.filter((m) => m.reply?.is_voice).length;
    const replyRate = totalSent ? Math.round((totalCompleted / totalSent) * 100) : 0;
    return { totalSent, totalCompleted, totalSkipped, voiceNotes, replyRate };
  }, [allMessages]);

  const feelingStats = useMemo(() => {
    const counts = {};
    allMessages.forEach((m) => {
      if (m.reply?.feeling) counts[m.reply.feeling] = (counts[m.reply.feeling] || 0) + 1;
    });
    return counts;
  }, [allMessages]);

  const medicineStats = useMemo(() => {
    let taken = 0, skipped = 0;
    allMessages.forEach((m) => {
      if (m.category?.includes("medicine")) {
        if (m.reply_status === "done" || m.replied) taken++;
        if (m.reply_status === "skipped") skipped++;
      }
    });
    return { taken, skipped };
  }, [allMessages]);

  const byType = useMemo(() => groupByCategory(allDays), [allDays]);

  const dayByDay = useMemo(() => {
    const map = {};
    allDays.forEach((d) => {
      if (!map[d.day_key]) map[d.day_key] = { day: d.day_key, messages: [], total: 0, completed: 0 };
      map[d.day_key].messages.push(...(d.messages || []));
      map[d.day_key].total += d.total || 0;
      map[d.day_key].completed += d.replied || 0;
    });
    return Object.values(map).sort((a, b) => b.day.localeCompare(a.day)).slice(0, 15);
  }, [allDays]);

  const [pdfBusy, setPdfBusy] = useState(false);
  const [sendBusy, setSendBusy] = useState(false);

  const handleDownloadPDF = async () => {
    if (!selectedParent) {
      toast.error("Select a parent first");
      return;
    }
    setPdfBusy(true);
    try {
      const parentName = selectedParent.name || "Parent";
      const period = selectedMonth;

      let jsPDF = null;
      try {
        const mod = await import("jspdf");
        jsPDF = mod.jsPDF || mod.default || mod;
      } catch {}

      if (!jsPDF) {
        try {
          if (!window.jspdf) {
            await new Promise((resolve, reject) => {
              const script = document.createElement("script");
              script.src = "https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js";
              script.onload = resolve;
              script.onerror = reject;
              document.head.appendChild(script);
            });
          }
          jsPDF = window.jspdf?.jsPDF || window.jsPDF;
        } catch {}
      }

      if (!jsPDF) {
        toast.error("PDF library not loaded. Run: npm install jspdf");
        return;
      }

      const doc = new jsPDF();
      let y = 20;
      doc.setFontSize(18);
      doc.setTextColor(44, 76, 59);
      doc.text(`AYANA Care Report - ${parentName}`, 14, y);
      y += 8;
      doc.setFontSize(11);
      doc.setTextColor(100, 100, 100);
      doc.text(`${monthLabel} (${period}) | Generated: ${new Date().toLocaleString()}`, 14, y);
      y += 8;
      doc.text(`Messages: ${stats.totalSent} | Completed: ${stats.totalCompleted} | Rate: ${stats.replyRate}% | Voice: ${stats.voiceNotes}`, 14, y);
      y += 8;
      doc.text(`Medicine: Taken ${medicineStats.taken} Skipped ${medicineStats.skipped}`, 14, y);
      y += 12;

      doc.setTextColor(0, 0, 0);
      doc.setFontSize(13);
      doc.text("By message type", 14, y);
      y += 8;
      doc.setFontSize(10);
      byType.forEach((row) => {
        if (y > 270) { doc.addPage(); y = 20; }
        doc.text(`${row.label.replace(/_/g, " ")} - Delivered: ${row.sent} Completed: ${row.completed}`, 14, y);
        y += 6;
      });

      y += 6;
      doc.setFontSize(13);
      doc.text("Day by day", 14, y);
      y += 8;
      doc.setFontSize(9);
      dayByDay.forEach((d) => {
        if (y > 275) { doc.addPage(); y = 20; }
        const msgs = (d.messages || []).slice(0, 6).map((m) => `${m.time || ""} ${m.category || ""}${m.replied ? " ✓" : ""}`).join(", ");
        const line = `${d.day} - ${d.completed}/${d.total} - ${msgs}`;
        const split = doc.splitTextToSize(line, 180);
        doc.text(split, 14, y);
        y += split.length * 5 + 2;
      });

      doc.save(`AYANA-Report-${parentName}-${period}.pdf`);
      toast.success(`${parentName} - ${monthLabel} PDF downloaded`);
    } catch (e) {
      console.error(e);
      toast.error("PDF failed: " + (e.message || "unknown"));
    } finally {
      setPdfBusy(false);
    }
  };

  const handleSendReport = async () => {
    if (!selectedParent) return;
    setSendBusy(true);
    try {
      const csrf = document.cookie.match(/csrf_token=([^;]+)/)?.[1] || localStorage.getItem("csrf_token") || "";
      const res = await fetch(`/api/reports/monthly/generate?parent_id=${selectedParentId}&period=${selectedMonth}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(csrf ? { "X-CSRF-Token": csrf } : {}),
        },
        credentials: "include",
      });
      if (!res.ok) {
        const err = await res.text();
        throw new Error(err);
      }
      const data = await res.json();
      toast.success(`Report for ${selectedParent.name} ${monthLabel} generated. If storage enabled, WhatsApp PDF will be sent to child + siblings.`);
      console.log("Generated report", data);
    } catch (e) {
      console.error(e);
      toast.error("Send failed: " + e.message);
    } finally {
      setSendBusy(false);
    }
  };

  if (!parentOptions.length) {
    return (
      <div className="bg-white rounded-xl border p-8 text-center">
        <p className="text-ayana-muted">No parents found. Add a parent first.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Controls: Parent + Month + Actions */}
      <div className="bg-white rounded-xl border border-ayana-line p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <User className="w-4 h-4 text-ayana-muted" />
            <select
              value={selectedParentId}
              onChange={(e) => setSelectedParentId(e.target.value)}
              className="px-4 py-2 rounded-full border border-ayana-line bg-white text-sm font-medium focus:outline-none focus:ring-2 focus:ring-ayana-bright/40"
            >
              {parentOptions.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-ayana-muted" />
            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(e.target.value)}
              className="px-4 py-2 rounded-full border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-bright/40"
            >
              {monthOptions.map((m) => {
                const [y, mo] = m.split("-").map(Number);
                const label = new Date(y, mo - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
                return <option key={m} value={m}>{label}</option>;
              })}
            </select>
          </div>

          <span className="text-xs text-ayana-muted ml-2">
            {stats.totalCompleted}/{stats.totalSent} completed • {monthLabel}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button onClick={handleSendReport} disabled={sendBusy} className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-ayana-line bg-white text-sm font-medium hover:bg-ayana-alt disabled:opacity-50">
            {sendBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />} Send to Child
          </button>
          <button onClick={handleDownloadPDF} disabled={pdfBusy} className="inline-flex items-center gap-2 px-5 py-2 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50">
            {pdfBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />} Download PDF
          </button>
        </div>
      </div>

      {/* Stats for SELECTED parent only */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <BarChart3 className="w-4 h-4 text-ayana-primary mb-3" />
          <p className="font-display text-2xl font-semibold">{stats.totalSent}</p>
          <p className="text-sm text-ayana-muted">Messages sent</p>
          <p className="text-xs text-ayana-muted mt-1">{selectedParent?.name} • {monthLabel}</p>
        </div>
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <CheckCircle2 className="w-4 h-4 text-ayana-primary mb-3" />
          <p className="font-display text-2xl font-semibold">{stats.replyRate}%</p>
          <p className="text-sm text-ayana-muted">Completion rate</p>
          <p className="text-xs text-ayana-muted mt-1">{stats.totalCompleted} completed</p>
        </div>
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <Clock className="w-4 h-4 text-ayana-primary mb-3" />
          <p className="font-display text-2xl font-semibold">{stats.totalSkipped}</p>
          <p className="text-sm text-ayana-muted">Skipped</p>
        </div>
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <MessageCircle className="w-4 h-4 text-ayana-primary mb-3" />
          <p className="font-display text-2xl font-semibold">{stats.voiceNotes}</p>
          <p className="text-sm text-ayana-muted">Voice notes</p>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <p className="text-sm font-medium flex items-center gap-2"><Smile className="w-4 h-4" /> How they responded</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.keys(feelingStats).length === 0 ? (
              <span className="text-ayana-muted text-xs">No feelings recorded yet</span>
            ) : (
              Object.entries(feelingStats).map(([feeling, count]) => (
                <span key={feeling} className="px-2.5 py-1 rounded-full bg-ayana-alt text-xs">{feeling.replace(/_/g, " ")} • {count}</span>
              ))
            )}
          </div>
        </div>
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <p className="text-sm font-medium flex items-center gap-2"><Pill className="w-4 h-4" /> Medicine</p>
          <p className="mt-3 text-sm">Taken {medicineStats.taken} <span className="text-ayana-muted">Skipped {medicineStats.skipped}</span></p>
        </div>
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <p className="text-sm font-medium flex items-center gap-2"><AlertCircle className="w-4 h-4" /> Attention alerts</p>
          <p className="mt-3 text-sm">0 flagged</p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-ayana-line p-6">
        <h3 className="font-display text-lg font-medium mb-4">By message type - {selectedParent?.name}</h3>
        <div className="grid grid-cols-3 text-xs text-ayana-muted pb-2 border-b">
          <span>Message</span><span className="text-right">Delivered</span><span className="text-right">Completed</span>
        </div>
        {byType.map((row) => (
          <div key={row.label} className="grid grid-cols-3 text-sm py-2 border-b last:border-0">
            <span className="capitalize">{row.label.replace(/_/g, " ")}</span>
            <span className="text-right">{row.sent}</span>
            <span className="text-right">{row.completed}</span>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-ayana-line p-6">
        <h3 className="font-display text-lg font-medium mb-4">Day by day - {selectedParent?.name}</h3>
        <div className="space-y-2">
          {dayByDay.map((d) => (
            <div key={d.day} className="flex items-center gap-3 text-sm">
              <span className="w-14 text-ayana-muted shrink-0">{d.day.slice(5)}</span>
              <div className="flex flex-wrap gap-1.5 flex-1">
                {(d.messages || []).map((m) => (
                  <span key={m.id} className="inline-flex px-2.5 py-1 rounded-full bg-ayana-alt text-xs">
                    {m.time} {m.category?.replace(/_/g, " ")} {m.replied ? "✓" : ""}
                  </span>
                ))}
              </div>
              <span className="text-xs shrink-0">{d.completed}/{d.total}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

