// Mirrors backend/validation.py — keep the two in sync.
export const PHONE_RULES = {
  "+91": [10], "+1": [10], "+44": [10], "+971": [9], "+65": [8], "+61": [9],
  "+49": [10, 11], "+33": [9], "+64": [8, 9, 10], "+977": [10], "+60": [9, 10],
  "+974": [8], "+966": [9],
};
const DIAL_CODES = Object.keys(PHONE_RULES).sort((a, b) => b.length - a.length);

// Returns "" when valid, else a friendly message.
export function phoneError(phone) {
  const p = (phone || "").replace(/[\s\-()]/g, "");
  if (!/^\+\d{7,15}$/.test(p)) return "Enter your number with digits only.";
  const code = DIAL_CODES.find((c) => p.startsWith(c));
  if (!code) return "";
  const national = p.slice(code.length);
  const want = PHONE_RULES[code];
  if (!want.includes(national.length)) {
    return `A ${code} number needs ${want.join(" or ")} digits (you entered ${national.length}).`;
  }
  if (national.startsWith("0")) return "Drop the leading 0 from the number.";
  return "";
}

export function passwordChecks(pw = "") {
  return [
    { ok: pw.length >= 8, label: "At least 8 characters" },
    { ok: /[A-Z]/.test(pw), label: "One uppercase letter" },
    { ok: /\d/.test(pw), label: "One number" },
  ];
}

export function passwordError(pw) {
  const failing = passwordChecks(pw).find((c) => !c.ok);
  return failing ? `Password needs: ${failing.label.toLowerCase()}.` : "";
}

// 0..4 strength score for the meter (symbols/length add bonus).
export function passwordScore(pw = "") {
  let s = passwordChecks(pw).filter((c) => c.ok).length;
  if (pw.length >= 12 || /[^A-Za-z0-9]/.test(pw)) s += 1;
  return Math.min(s, 4);
}
