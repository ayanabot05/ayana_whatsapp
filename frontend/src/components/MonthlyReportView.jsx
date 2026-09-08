import { useMemo, useState, useEffect } from "react";
import { BarChart3, CheckCircle2, Clock, MessageCircle, Smile, Pill, AlertCircle, TrendingUp, Download, Loader2, Calendar } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";
import { toast } from "sonner";

function groupByCategory(days) {
  const map = {};
  days.forEach((d) => {
    d.messages.forEach((m) => {
      if (!map[m.category]) map[m.category] = { sent: 0, completed: 0, label: m.category };
      map[m.category].sent += 1;
      if (m.replied || m.reply_status === "done") map[m.category].completed += 1;
    });
  });
  return Object.values(map);
}

const todayIso = () => new Date().toISOString().slice(0, 10);

export function MonthlyReportView({ parents, plan, user, checkinsData }) {
  // All hooks MUST be called before any early return - React rules-of-hooks

  // Every distinct month present in the data (plus the current month), newest first.
  const monthOptions = useMemo(() => {
    const set = new Set();
    const today = todayIso();
    (checkinsData?.parents || []).forEach((p) =>
      (p.days || []).forEach((d) => {
        const iso = d.day_key === "today" ? today : d.day_key;
        if (iso && iso.length >= 7) set.add(iso.slice(0, 7));
      })
    );
    set.add(today.slice(0, 7));
    return Array.from(set).sort().reverse();
  }, [checkinsData]);

  const [selectedMonth, setSelectedMonth] = useState(() => todayIso().slice(0, 7));

  // Keep the selection valid if the available months change (e.g. data loads in later).
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
    if (!checkinsData?.parents?.length) return [];
    const today = todayIso();
    return checkinsData.parents.flatMap((p) =>
      (p.days || [])
        .map((d) => ({ ...d, parentName: p.name, parentId: p.parent_id, _iso: d.day_key === "today" ? today : d.day_key }))
        .filter((d) => d._iso && d._iso.slice(0, 7) === selectedMonth)
    );
  }, [checkinsData, selectedMonth]);

  const allMessages = useMemo(() => allDays.flatMap((d) => d.messages), [allDays]);

  const stats = useMemo(() => {
    const totalSent = allMessages.length;
    const totalCompleted = allMessages.filter((m) => m.replied || m.reply_status === "done").length;
    const totalSkipped = allMessages.filter((m) => m.reply_status === "skipped").length;
    const voiceNotes = allMessages.filter((m) => m.reply?.is_voice).length;
    const replyRate = totalSent ? Math.round((totalCompleted / totalSent) * 100) : 0;
    const scheduled = totalSent;
    return { totalSent, totalCompleted, totalSkipped, voiceNotes, replyRate, scheduled };
  }, [allMessages]);

  const feelingStats = useMemo(() => {
    const counts = {};
    allMessages.forEach((m) => {
      if (m.reply?.feeling) {
        counts[m.reply.feeling] = (counts[m.reply.feeling] || 0) + 1;
      }
    });
    return counts;
  }, [allMessages]);

  const medicineStats = useMemo(() => {
    let taken = 0, skipped = 0;
    allMessages.forEach((m) => {
      if (m.category.includes("medicine")) {
        if (m.reply_status === "done" || m.replied) taken++;
        if (m.reply_status === "skipped") skipped++;
      }
    });
    return { taken, skipped };
  }, [allMessages]);

  const byType = useMemo(() => groupByCategory(allDays), [allDays]);

  const dayByDay = useMemo(() => {
    // group by day_key across all parents, within the selected month
    const map = {};
    allDays.forEach((d) => {
      if (!map[d.day_key]) map[d.day_key] = { day: d.day_key, messages: [], total: 0, completed: 0 };
      map[d.day_key].messages.push(...d.messages);
      map[d.day_key].total += d.total;
      map[d.day_key].completed += d.replied;
    });
    return Object.values(map).sort((a, b) => b.day.localeCompare(a.day)).slice(0, 10);
  }, [allDays]);

  const [pdfBusy, setPdfBusy] = useState(false);

  // Draws the AYANA logo, large and faint, centered on the current page — behind the content.
  const addWatermark = (doc, logoData) => {
    if (!logoData) return;
    try {
      const pageWidth = doc.internal.pageSize.getWidth();
      const pageHeight = doc.internal.pageSize.getHeight();
      const size = Math.min(pageWidth, pageHeight) * 0.62;
      const x = (pageWidth - size) / 2;
      const y = (pageHeight - size) / 2;
      if (doc.GState && doc.saveGraphicsState) {
        doc.saveGraphicsState();
        doc.setGState(new doc.GState({ opacity: 0.06 }));
        doc.addImage(logoData, "PNG", x, y, size, size);
        doc.restoreGraphicsState();
      } else {
        // Fallback if this jsPDF build has no GState support - draw it small in a corner instead
        // of a full faint overlay, so it never overwhelms the report text.
        doc.addImage(logoData, "PNG", pageWidth - 34, pageHeight - 34, 20, 20);
      }
    } catch (e) {
      console.warn("Failed to draw watermark", e);
    }
  };

  const handleDownloadPDF = async () => {
    setPdfBusy(true);
    try {
      const parentName = checkinsData.parents[0]?.name || "Parent";
      const period = selectedMonth;

      // Load jsPDF - first try npm package, then CDN fallback (no warning)
      let jsPDF = null;
      try {
        // @ts-ignore - dynamic, may not be installed
        const mod = await import(/* webpackIgnore: true */ "jspdf");
        jsPDF = mod.jsPDF || mod.default || mod;
      } catch {}

      if (!jsPDF) {
        // CDN fallback - load from cdnjs if npm package not installed
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
        // Final fallback - use browser print
        window.print();
        toast("PDF: Use your browser's Print → Save as PDF (install jspdf to remove this step: npm install jspdf)", { duration: 5000 });
        return;
      }

      const doc = new jsPDF();

      // --- LOAD LOGO from public folder ---
      // Your logo is at frontend/public/ayana_logo.png -> available at /ayana_logo.png
      let logoData = null;
      try {
        const tryPaths = ["/ayana_logo.png", "/ayana_logo", "/logo.png", "/AYANA.png"];
        for (const p of tryPaths) {
          try {
            const res = await fetch(p);
            if (res.ok) {
              const blob = await res.blob();
              logoData = await new Promise((resolve) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result);
                reader.readAsDataURL(blob);
              });
              if (logoData) break;
            }
          } catch {}
        }
      } catch (e) {
        console.warn("Logo not found for PDF", e);
      }

      let y = 20;
      // Add logo if loaded
      if (logoData) {
        try {
          // Logo at top-left, keep aspect ratio, height 22mm
          doc.addImage(logoData, "PNG", 14, 10, 32, 18);
          y = 32;
        } catch (e) {
          console.warn("Failed to add logo to PDF", e);
          y = 20;
        }
      }

      doc.setFontSize(18);
      doc.setTextColor(44, 76, 59); // ayana primary green
      doc.text(`AYANA Care Report - ${parentName} - ${monthLabel}`, 14, y);
      y += 10;
      doc.setFontSize(11);
      doc.setTextColor(100, 100, 100);
      doc.text(`Generated: ${new Date().toLocaleString()} | Source: Dashboard live data (same as Check-ins tab)`, 14, y);
      y += 10;
      doc.text(`Messages sent: ${stats.totalSent} | Completed: ${stats.totalCompleted} | Completion: ${stats.replyRate}% | Voice notes: ${stats.voiceNotes}`, 14, y);
      y += 10;
      doc.text(`Medicine: Taken ${medicineStats.taken} Skipped ${medicineStats.skipped} | Alerts: ${checkinsData.alerts?.length || 0}`, 14, y);
      y += 12;

      doc.setTextColor(0, 0, 0);
      doc.setFontSize(13);
      doc.text("By message type", 14, y);
      y += 8;
      doc.setFontSize(10);
      if (byType.length === 0) {
        doc.text("No data for this month.", 14, y);
        y += 6;
      }
      byType.forEach((row) => {
        if (y > 270) { doc.addPage(); y = 20; }
        doc.text(`${row.label.replace(/_/g, " ")} - Delivered: ${row.sent} Completed: ${row.completed}`, 14, y);
        y += 6;
      });
      y += 6;
      doc.setFontSize(13);
      doc.text("Day by day", 14, y);
      y += 8;
      doc.setFontSize(10);
      if (dayByDay.length === 0) {
        doc.text("No check-ins recorded for this month.", 14, y);
        y += 6;
      }
      dayByDay.forEach((d) => {
        if (y > 270) { doc.addPage(); y = 20; }
        const line = `${d.day} - ${d.completed}/${d.total} - ${d.messages.map((m) => `${m.time} ${m.category}`).join(", ")}`;
        const split = doc.splitTextToSize(line, 180);
        doc.text(split, 14, y);
        y += split.length * 6;
      });

      // Watermark + footer with AYANA branding on every page
      const pageCount = doc.internal.getNumberOfPages();
      for (let i = 1; i <= pageCount; i++) {
        doc.setPage(i);
        addWatermark(doc, logoData);
        doc.setFontSize(9);
        doc.setTextColor(150, 150, 150);
        doc.text(`AYANA - Caring for Amma/Nanna | ayana.care | Page ${i}/${pageCount}`, 14, 285);
      }

      doc.save(`AYANA-Report-${parentName}-${period}.pdf`);
      toast.success(`${monthLabel} report downloaded with AYANA watermark.`);
    } catch (e) {
      console.error(e);
      toast.error("PDF generation failed: " + (e.message || "unknown error"));
    } finally {
      setPdfBusy(false);
    }
  };

  // Early return AFTER all hooks - safe now
  if (!checkinsData?.parents?.length) {
    return (
      <div className="space-y-6">
        <EmptyState text="No check-ins yet. Reports will appear once messages start going out — using the same data as your Check-ins tab." />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <p className="text-xs text-ayana-muted">Source: Dashboard bootstrap — same as Check-ins tab ({stats.totalCompleted}/{stats.totalSent})</p>
          <p className="text-xs text-ayana-muted mt-0.5">Showing <span className="font-medium text-ayana-text">{monthLabel}</span></p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Calendar className="w-3.5 h-3.5 text-ayana-muted absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(e.target.value)}
              data-testid="report-month-select"
              className="pl-8 pr-8 py-2 rounded-full border border-ayana-line bg-white text-sm text-ayana-text focus:outline-none focus:ring-2 focus:ring-ayana-bright/40 focus:border-ayana-bright transition appearance-none"
            >
              {monthOptions.map((m) => {
                const [y, mo] = m.split("-").map(Number);
                const label = new Date(y, mo - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
                return <option key={m} value={m}>{label}</option>;
              })}
            </select>
          </div>
          <button onClick={handleDownloadPDF} disabled={pdfBusy} className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-ayana-primary text-white text-sm font-medium hover:bg-ayana-primary-hover disabled:opacity-50" data-testid="download-report-pdf">
            {pdfBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />} Download PDF
          </button>
        </div>
      </div>
      {/* Top stats - in sync with Check-ins tab */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <BarChart3 className="w-4 h-4 text-ayana-primary mb-3" />
          <p className="font-display text-2xl font-semibold">{stats.totalSent}</p>
          <p className="text-sm text-ayana-muted">Messages sent</p>
          <p className="text-xs text-ayana-muted mt-1">{stats.scheduled} scheduled</p>
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
          <p className="text-xs text-ayana-muted mt-1">quiet-hours / paused</p>
        </div>
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <MessageCircle className="w-4 h-4 text-ayana-primary mb-3" />
          <p className="font-display text-2xl font-semibold">{stats.voiceNotes}</p>
          <p className="text-sm text-ayana-muted">Voice notes</p>
          <p className="text-xs text-ayana-muted mt-1">{checkinsData.parents.length} parent{checkinsData.parents.length > 1 ? "s" : ""} active</p>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <p className="text-sm font-medium flex items-center gap-2"><Smile className="w-4 h-4" /> How they responded</p>
          <div className="mt-3 flex gap-3 text-sm">
            {Object.keys(feelingStats).length === 0 ? (
              <span className="text-ayana-muted text-xs">No feelings recorded yet</span>
            ) : (
              Object.entries(feelingStats).map(([feeling, count]) => (
                <span key={feeling} className="px-2.5 py-1 rounded-full bg-ayana-alt text-ayana-text">{feeling.replace(/_/g, " ")} · {count}</span>
              ))
            )}
          </div>
        </div>
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <p className="text-sm font-medium flex items-center gap-2"><Pill className="w-4 h-4" /> Medicine</p>
          <p className="mt-3 text-sm text-ayana-text">Taken {medicineStats.taken} <span className="text-ayana-muted">Skipped {medicineStats.skipped}</span></p>
        </div>
        <div className="bg-white rounded-xl border border-ayana-line p-5">
          <p className="text-sm font-medium flex items-center gap-2"><AlertCircle className="w-4 h-4" /> Attention alerts</p>
          <p className="mt-3 text-sm text-ayana-text">{checkinsData.alerts?.length || 0} flagged messages</p>
        </div>
      </div>

      {/* By message type - now using same categories as Check-ins */}
      <div className="bg-white rounded-xl border border-ayana-line p-6">
        <h3 className="font-display text-lg font-medium mb-4">By message type</h3>
        <div className="space-y-3">
          <div className="grid grid-cols-3 text-xs text-ayana-muted pb-2 border-b border-ayana-line">
            <span>Message</span>
            <span className="text-right">Delivered</span>
            <span className="text-right">Completed</span>
          </div>
          {byType.length === 0 ? (
            <p className="text-sm text-ayana-muted py-2">No data for {monthLabel}</p>
          ) : (
            byType.map((row) => (
              <div key={row.label} className="grid grid-cols-3 text-sm py-2 border-b border-ayana-line/50 last:border-0">
                <span className="text-ayana-text capitalize">{row.label.replace(/_/g, " ")}</span>
                <span className="text-right text-ayana-secondary">{row.sent}</span>
                <span className="text-right text-ayana-secondary">{row.completed}</span>
              </div>
            ))
          )}
        </div>
        <p className="text-[11px] text-ayana-muted mt-3">Source: dashboard bootstrap /checkins - same as Check-ins tab</p>
      </div>

      {/* Day by day - in sync */}
      <div className="bg-white rounded-xl border border-ayana-line p-6">
        <h3 className="font-display text-lg font-medium mb-4">Day by day</h3>
        <div className="space-y-2">
          {dayByDay.length === 0 ? (
            <p className="text-sm text-ayana-muted py-2">No check-ins recorded for {monthLabel}</p>
          ) : (
            dayByDay.map((d) => (
              <div key={d.day} className="flex items-center gap-3 text-sm">
                <span className="w-14 text-ayana-muted shrink-0">{d.day.slice(5)}</span>
                <div className="flex flex-wrap gap-1.5 flex-1">
                  {d.messages.map((m) => (
                    <span key={m.id} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-ayana-alt text-xs text-ayana-secondary">
                      {m.time} {m.category.replace(/_/g, " ")} {m.replied || m.reply_status === "done" ? "✓" : ""}
                    </span>
                  ))}
                </div>
                <span className="text-xs text-ayana-muted shrink-0">{d.completed}/{d.total}</span>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-ayana-line p-6">
        <h3 className="font-display text-lg font-medium flex items-center gap-2"><TrendingUp className="w-4 h-4" /> Mood this month</h3>
        <p className="text-sm text-ayana-muted mt-2">
          {allDays.length < 2 ? "Not enough check-ins yet this month for a trend." : `Based on ${stats.totalCompleted} completed check-ins this period.`}
        </p>
      </div>
    </div>
  );
}