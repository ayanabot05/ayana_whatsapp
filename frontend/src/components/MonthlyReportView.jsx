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

      // ---------------------------------------------------------------
      // Styled report layout (mirrors the dashboard's printed report:
      // header, stat cards, info row, message-type table, day-by-day
      // pills, footer disclaimer) instead of a flat text dump.
      // ---------------------------------------------------------------
      const doc = new jsPDF({ unit: "mm", format: "a4" });
      const pageW = doc.internal.pageSize.getWidth();
      const pageH = doc.internal.pageSize.getHeight();
      const marginX = 14;
      const contentW = pageW - marginX * 2;

      const primary = [44, 76, 59];        // dark green (brand)
      const primarySoft = [232, 242, 236]; // light green fill
      const border = [224, 224, 224];
      const rowAlt = [248, 248, 248];
      const muted = [120, 120, 120];
      const text = [30, 30, 30];

      let y = 0;

      const drawFooter = () => {
        doc.setDrawColor(...border);
        doc.line(marginX, pageH - 14, pageW - marginX, pageH - 14);
        doc.setFontSize(7);
        doc.setTextColor(...muted);
        doc.text(
          "AYANA is not an emergency or medical service. This report summarises WhatsApp check-in activity only.",
          marginX,
          pageH - 9
        );
        doc.text("ayanabott.com", pageW - marginX, pageH - 9, { align: "right" });
      };

      const ensureSpace = (needed) => {
        if (y + needed > pageH - 18) {
          drawFooter();
          doc.addPage();
          y = 16;
        }
      };

      // ---- Header ----
      doc.setFillColor(...primary);
      doc.roundedRect(marginX, 14, 10, 10, 2, 2, "F");
      doc.setFontSize(9);
      doc.setTextColor(255, 255, 255);
      doc.setFont(undefined, "bold");
      doc.text("A", marginX + 5, 20.6, { align: "center" });
      doc.setFont(undefined, "normal");

      doc.setFontSize(8.5);
      doc.setTextColor(...muted);
      doc.text("MONTHLY CARE REPORT", marginX + 14, 17.5);

      doc.setFontSize(17);
      doc.setTextColor(...text);
      doc.setFont(undefined, "bold");
      doc.text(`${parentName} \u00b7 ${monthLabel}`, marginX + 14, 24.5);
      doc.setFont(undefined, "normal");

      doc.setFontSize(8.5);
      doc.setTextColor(...muted);
      doc.text(`Generated ${new Date().toLocaleString()}`, pageW - marginX, 17.5, { align: "right" });
      doc.setFontSize(10);
      doc.setTextColor(...primary);
      doc.setFont(undefined, "bold");
      doc.text("AYANA", pageW - marginX, 23, { align: "right" });
      doc.setFont(undefined, "normal");

      y = 30;
      doc.setDrawColor(...border);
      doc.line(marginX, y, pageW - marginX, y);
      y += 8;

      // ---- Row 1: headline stat cards ----
      const cardGap = 4;
      const cardW = (contentW - cardGap * 3) / 4;
      const drawStatCard = (x, value, label, sub) => {
        doc.setDrawColor(...border);
        doc.roundedRect(x, y, cardW, 22, 2, 2);
        doc.setFontSize(15);
        doc.setTextColor(...text);
        doc.setFont(undefined, "bold");
        doc.text(String(value), x + 4, y + 10);
        doc.setFont(undefined, "normal");
        doc.setFontSize(8.5);
        doc.setTextColor(...muted);
        doc.text(label, x + 4, y + 15.5);
        if (sub) {
          doc.setFontSize(7.5);
          doc.text(sub, x + 4, y + 19.5);
        }
      };
      drawStatCard(marginX, stats.totalSent, "Messages sent", monthLabel);
      drawStatCard(marginX + (cardW + cardGap), `${stats.replyRate}%`, "Completion rate", `${stats.totalCompleted} completed`);
      drawStatCard(marginX + (cardW + cardGap) * 2, stats.totalSkipped, "Skipped", null);
      drawStatCard(marginX + (cardW + cardGap) * 3, stats.voiceNotes, "Voice notes", null);
      y += 22 + 6;

      // ---- Row 2: feelings / medicine / attention ----
      const row2W = (contentW - cardGap * 2) / 3;
      const drawInfoCard = (x, title, body) => {
        doc.setDrawColor(...border);
        doc.roundedRect(x, y, row2W, 20, 2, 2);
        doc.setFontSize(8.5);
        doc.setTextColor(...text);
        doc.setFont(undefined, "bold");
        doc.text(title, x + 4, y + 6.5);
        doc.setFont(undefined, "normal");
        doc.setFontSize(8);
        doc.setTextColor(...muted);
        doc.text(body, x + 4, y + 13, { maxWidth: row2W - 8 });
      };
      const feelingsLine = Object.keys(feelingStats).length
        ? Object.entries(feelingStats).map(([f, c]) => `${f.replace(/_/g, " ")} \u00d7${c}`).join("   ")
        : "No feelings recorded yet";
      drawInfoCard(marginX, "How they responded", feelingsLine);
      drawInfoCard(marginX + row2W + cardGap, "Medicine", `Taken ${medicineStats.taken}   Skipped ${medicineStats.skipped}`);
      drawInfoCard(marginX + (row2W + cardGap) * 2, "Attention alerts", "0 flagged");
      y += 20 + 10;

      // ---- By message type table ----
      ensureSpace(16 + byType.length * 7);
      doc.setFontSize(12);
      doc.setTextColor(...text);
      doc.setFont(undefined, "bold");
      doc.text(`By message type \u2014 ${parentName}`, marginX, y);
      doc.setFont(undefined, "normal");
      y += 6;

      doc.setFillColor(...primarySoft);
      doc.rect(marginX, y, contentW, 7, "F");
      doc.setFontSize(8.5);
      doc.setTextColor(...muted);
      doc.text("Message", marginX + 3, y + 5);
      doc.text("Delivered", marginX + contentW - 40, y + 5, { align: "right" });
      doc.text("Completed", marginX + contentW - 3, y + 5, { align: "right" });
      y += 7;

      doc.setFontSize(9);
      byType.forEach((row, i) => {
        ensureSpace(8);
        if (i % 2 === 1) {
          doc.setFillColor(...rowAlt);
          doc.rect(marginX, y, contentW, 7, "F");
        }
        doc.setTextColor(...text);
        doc.text(row.label.replace(/_/g, " "), marginX + 3, y + 5);
        doc.text(String(row.sent), marginX + contentW - 40, y + 5, { align: "right" });
        doc.text(String(row.completed), marginX + contentW - 3, y + 5, { align: "right" });
        doc.setDrawColor(...border);
        doc.line(marginX, y + 7, marginX + contentW, y + 7);
        y += 7;
      });
      y += 10;

      // ---- Day by day ----
      ensureSpace(16);
      doc.setFontSize(12);
      doc.setFont(undefined, "bold");
      doc.setTextColor(...text);
      doc.text(`Day by day \u2014 ${parentName}`, marginX, y);
      doc.setFont(undefined, "normal");
      y += 8;

      dayByDay.forEach((d) => {
        ensureSpace(12);
        doc.setFontSize(8.5);
        doc.setTextColor(...muted);
        doc.text(d.day.slice(5), marginX, y + 4);
        doc.setTextColor(...text);
        doc.text(`${d.completed}/${d.total}`, marginX + contentW, y + 4, { align: "right" });

        let px = marginX + 16;
        let pillRowY = y;
        (d.messages || []).forEach((m) => {
          const label = `${m.time || ""} ${(m.category || "").replace(/_/g, " ")}${m.replied ? " \u2713" : ""}`.trim();
          doc.setFontSize(7);
          const w = doc.getTextWidth(label) + 5;
          if (px + w > marginX + contentW - 18) {
            px = marginX + 16;
            pillRowY += 6;
            ensureSpace(10);
          }
          doc.setFillColor(...primarySoft);
          doc.roundedRect(px, pillRowY - 3.5, w, 5.5, 2, 2, "F");
          doc.setTextColor(...primary);
          doc.text(label, px + 2.5, pillRowY + 0.5);
          px += w + 2;
        });
        y = pillRowY + 9;
      });

      drawFooter();
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