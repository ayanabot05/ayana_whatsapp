// src/lib/generateMonthlyReportPdf.js
//
// Redraws the styled "Monthly Care Report" entirely with jsPDF vector
// primitives (rounded panels, rules, a mood-chart line, message pills,
// and a disclaimer footer) so the PDF matches the branded on-screen
// report without opening a print dialog or rasterizing a screenshot.
//
// Usage:
//   import { generateMonthlyReportPDF } from "@/lib/generateMonthlyReportPdf";
//   const doc = generateMonthlyReportPDF(jsPDF, { ...data });
//   doc.save("report.pdf");

function hex(h) {
  const c = h.replace("#", "");
  return [parseInt(c.slice(0, 2), 16), parseInt(c.slice(2, 4), 16), parseInt(c.slice(4, 6), 16)];
}

const COLORS = {
  ink: hex("#1a1a1a"),
  muted: hex("#6b5f4a"),
  muted2: hex("#9a9183"),
  cream: hex("#faf6ec"),
  border: hex("#efe8d8"),
  brand: hex("#0f3d2e"),
  mint: hex("#10b981"),
  mintBg: hex("#e6f4ea"),
  mintBorder: hex("#c8e9d4"),
  amber: hex("#f59e0b"),
  white: [255, 255, 255],
};

function setFill(doc, c) { doc.setFillColor(c[0], c[1], c[2]); }
function setDraw(doc, c) { doc.setDrawColor(c[0], c[1], c[2]); }
function setText(doc, c) { doc.setTextColor(c[0], c[1], c[2]); }

function drawPanel(doc, x, y, w, h) {
  setFill(doc, COLORS.white);
  setDraw(doc, COLORS.border);
  doc.setLineWidth(0.75);
  doc.roundedRect(x, y, w, h, 6, 6, "FD");
}

function addFooter(doc, pageW, pageH, margin) {
  const y = pageH - 44;
  setDraw(doc, COLORS.border);
  doc.setLineWidth(0.5);
  doc.line(margin, y, pageW - margin, y);
  setText(doc, COLORS.muted2);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(7);
  const disclaimer =
    "Disclaimer: AYANA is not an emergency or medical service. This report summarises WhatsApp " +
    "check-in activity only and is not a health assessment. In a crisis, contact local emergency " +
    "services or your parent's doctor immediately.";
  const lines = doc.splitTextToSize(disclaimer, pageW - margin * 2 - 14);
  doc.text(lines, margin, y + 12);
  setText(doc, COLORS.muted2);
  doc.setFontSize(7);
  doc.text("\u00a9 2026 AYANA \u00b7 ayanabott.com", margin, y + 12 + lines.length * 8 + 4);
}

/**
 * @param {Function} jsPDFCtor  the jsPDF constructor (from `import("jspdf")` or the CDN global)
 * @param {object} data
 * @param {string} data.parentName
 * @param {string} [data.relationship]
 * @param {string} [data.phone]
 * @param {string} data.monthLabel
 * @param {string} [data.preparedFor]
 * @param {string} data.generatedAt
 * @param {object} data.stats  { totalSent, scheduledCount, replyRate, repliedCount, skipped, voiceNotes, activeDays }
 * @param {Array<{label:string,count:number}>} [data.feelingStats]
 * @param {{taken:number, skipped:number}} [data.medicineStats]
 * @param {number} [data.alertsCount]
 * @param {Array<{label:string, value:number}>} [data.moodPoints]  value 0=Not well,1=Okay,2=Good
 * @param {Array<{label:string, sent:number, replied:number}>} [data.byType]
 * @param {Array<{day:string, total:number, completed:number, items:Array<{time?:string,label:string,done:boolean}>}>} [data.dayByDay]
 * @returns {jsPDF} the finished document (call .save(filename) yourself)
 */
export function generateMonthlyReportPDF(jsPDFCtor, data) {
  const doc = new jsPDFCtor({ unit: "pt", format: "a4" });
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const margin = 40;
  const contentW = pageW - margin * 2;
  let y = margin;

  const checkPage = (needed) => {
    if (y + needed > pageH - 70) {
      addFooter(doc, pageW, pageH, margin);
      doc.addPage();
      y = margin;
    }
  };

  // ---------- Header ----------
  setFill(doc, COLORS.brand);
  doc.roundedRect(margin, y, 34, 34, 6, 6, "F");
  setText(doc, COLORS.white);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(14);
  doc.text("A", margin + 17, y + 22, { align: "center" });

  setText(doc, COLORS.muted2);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  doc.text("MONTHLY CARE REPORT", margin + 44, y + 10);

  setText(doc, COLORS.ink);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(19);
  doc.text(`${data.parentName || "Parent"} \u00b7 ${data.monthLabel || ""}`, margin + 44, y + 27);

  setText(doc, COLORS.muted);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(9);
  const subline = [data.relationship, data.phone].filter(Boolean).join(" \u00b7 ");
  if (subline) doc.text(subline, margin + 44, y + 39);

  setText(doc, COLORS.brand);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(10);
  doc.text("AYANA", pageW - margin, y + 8, { align: "right" });
  setText(doc, COLORS.muted2);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  if (data.preparedFor) doc.text(`Prepared for ${data.preparedFor}`, pageW - margin, y + 20, { align: "right" });
  doc.text(`Generated ${data.generatedAt || new Date().toLocaleString()}`, pageW - margin, y + 31, { align: "right" });

  y += 52;
  setDraw(doc, COLORS.border);
  doc.setLineWidth(1);
  doc.line(margin, y, pageW - margin, y);
  y += 18;

  // ---------- 4 stat cards ----------
  const s = data.stats || {};
  const cardGap = 10;
  const cardW = (contentW - cardGap * 3) / 4;
  const cardH = 64;
  const statCards = [
    { value: String(s.totalSent ?? 0), label: "Messages sent", sub: `${s.scheduledCount ?? s.totalSent ?? 0} scheduled` },
    { value: `${s.replyRate ?? 0}%`, label: "Reply rate", sub: `${s.repliedCount ?? 0} replies` },
    { value: String(s.skipped ?? 0), label: "Skipped", sub: "quiet-hours / paused" },
    { value: String(s.voiceNotes ?? 0), label: "Voice notes", sub: `${s.activeDays ?? 0} active days` },
  ];
  statCards.forEach((card, i) => {
    const x = margin + i * (cardW + cardGap);
    drawPanel(doc, x, y, cardW, cardH);
    setText(doc, COLORS.ink);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(18);
    doc.text(card.value, x + 12, y + 30);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.text(card.label, x + 12, y + 45);
    setText(doc, COLORS.muted2);
    doc.setFontSize(7.5);
    doc.text(card.sub, x + 12, y + 56);
  });
  y += cardH + 14;

  // ---------- 3 info cards ----------
  const card3W = (contentW - cardGap * 2) / 3;
  const card3H = 58;

  const feelingLine =
    data.feelingStats && data.feelingStats.length
      ? data.feelingStats.map((f) => `${f.label}: ${f.count}`).join("   ")
      : "No feelings recorded yet";
  const med = data.medicineStats || { taken: 0, skipped: 0 };

  [
    { title: "How they said they felt", body: feelingLine },
    { title: "Medicine", body: `Taken ${med.taken}   Skipped ${med.skipped}` },
    { title: "Attention alerts", body: `${data.alertsCount ?? 0} flagged messages` },
  ].forEach((card, i) => {
    const x = margin + i * (card3W + cardGap);
    drawPanel(doc, x, y, card3W, card3H);
    setText(doc, COLORS.ink);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(9);
    doc.text(card.title, x + 10, y + 16);
    doc.setFont("helvetica", "normal");
    setText(doc, COLORS.muted);
    doc.setFontSize(8.5);
    const bodyLines = doc.splitTextToSize(card.body, card3W - 20);
    doc.text(bodyLines, x + 10, y + 32);
  });
  y += card3H + 16;

  // ---------- Mood chart ----------
  const chartH = 130;
  checkPage(chartH + 20);
  drawPanel(doc, margin, y, contentW, chartH);
  setText(doc, COLORS.ink);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(10);
  doc.text("Mood this month", margin + 12, y + 18);
  setText(doc, COLORS.muted2);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  const moodSub =
    data.moodPoints && data.moodPoints.length
      ? "Daily mood based on how-are-you-feeling replies"
      : "Not enough check-ins yet this month for a trend.";
  doc.text(moodSub, margin + 12, y + 30);

  const chartLeft = margin + 60;
  const chartRight = margin + contentW - 20;
  const chartTop = y + 44;
  const chartBottom = y + chartH - 18;
  const chartWidth = chartRight - chartLeft;

  setDraw(doc, COLORS.border);
  doc.setLineWidth(0.75);
  [0, 0.5, 1].forEach((frac) => {
    const ly = chartTop + (chartBottom - chartTop) * frac;
    doc.line(chartLeft, ly, chartRight, ly);
  });
  doc.line(chartLeft, chartTop, chartLeft, chartBottom);

  setText(doc, COLORS.muted2);
  doc.setFontSize(7.5);
  doc.text("Good", chartLeft - 8, chartTop + 3, { align: "right" });
  doc.text("Okay", chartLeft - 8, (chartTop + chartBottom) / 2 + 3, { align: "right" });
  doc.text("Not well", chartLeft - 8, chartBottom + 3, { align: "right" });

  const points = data.moodPoints || [];
  if (points.length) {
    const n = points.length;
    let prevX = null, prevY = null;
    points.forEach((p, i) => {
      const px = n === 1 ? chartLeft + chartWidth / 2 : chartLeft + (chartWidth * i) / (n - 1);
      const py = chartBottom - (chartBottom - chartTop) * (Math.max(0, Math.min(2, p.value)) / 2);
      if (prevX !== null) {
        setDraw(doc, COLORS.mint);
        doc.setLineWidth(1);
        doc.line(prevX, prevY, px, py);
      }
      setDraw(doc, COLORS.mint);
      setFill(doc, COLORS.white);
      doc.setLineWidth(1.2);
      doc.circle(px, py, 2.6, "FD");
      setText(doc, COLORS.muted2);
      doc.setFontSize(6.5);
      doc.text(String(p.label || ""), px, chartBottom + 12, { align: "center" });
      prevX = px; prevY = py;
    });
  }
  y += chartH + 18;

  // ---------- By message type ----------
  const byType = data.byType || [];
  checkPage(30 + byType.length * 14);
  setText(doc, COLORS.ink);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(11);
  doc.text("By message type", margin, y);
  y += 10;
  setDraw(doc, COLORS.border);
  doc.setLineWidth(0.75);
  doc.line(margin, y, pageW - margin, y);
  y += 12;
  setText(doc, COLORS.muted2);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  doc.text("Message", margin, y);
  doc.text("Sent", pageW - margin - 90, y, { align: "right" });
  doc.text("Replied", pageW - margin, y, { align: "right" });
  y += 6;
  setDraw(doc, COLORS.border);
  doc.line(margin, y, pageW - margin, y);

  byType.forEach((row) => {
    checkPage(16);
    y += 16;
    setText(doc, COLORS.ink);
    doc.setFontSize(9);
    doc.text(row.label, margin, y);
    doc.text(String(row.sent), pageW - margin - 90, y, { align: "right" });
    doc.text(String(row.replied), pageW - margin, y, { align: "right" });
    setDraw(doc, COLORS.border);
    doc.setLineWidth(0.5);
    doc.line(margin, y + 5, pageW - margin, y + 5);
  });
  y += 26;

  // ---------- Day by day ----------
  const dayByDay = data.dayByDay || [];
  checkPage(30);
  setText(doc, COLORS.ink);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(11);
  doc.text("Day by day", margin, y);
  y += 16;

  dayByDay.forEach((d) => {
    checkPage(28);
    setText(doc, COLORS.muted);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(8.5);
    doc.text(d.day || "", margin, y + 8);

    setText(doc, COLORS.muted2);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(8);
    doc.text(`${d.completed ?? 0}/${d.total ?? 0}`, pageW - margin, y + 8, { align: "right" });

    let px = margin + 66;
    let py = y;
    const pillH = 14;
    (d.items || []).forEach((item) => {
      const label = `${item.time ? item.time + " " : ""}${item.label}${item.done ? " \u2713" : ""}`.trim();
      doc.setFontSize(7.5);
      const textW = doc.getTextWidth(label) + 12;
      if (px + textW > pageW - margin) {
        px = margin + 66;
        py += pillH + 4;
        checkPage(pillH + 8);
      }
      setDraw(doc, item.done ? COLORS.mintBorder : COLORS.border);
      setFill(doc, item.done ? COLORS.mintBg : COLORS.cream);
      doc.setLineWidth(0.75);
      doc.roundedRect(px, py, textW, pillH, 6, 6, "FD");
      setText(doc, item.done ? COLORS.brand : COLORS.muted);
      doc.text(label, px + 6, py + 9.5);
      px += textW + 4;
    });
    y = py + pillH + 10;
  });

  addFooter(doc, pageW, pageH, margin);
  return doc;
}