import { passwordChecks, passwordScore } from "@/lib/validation";

const LABELS = ["", "Weak", "Fair", "Good", "Strong"];
const COLORS = ["", "bg-red-400", "bg-amber-400", "bg-lime-500", "bg-green-600"];

export function PasswordStrength({ password, testid = "password-strength" }) {
  if (!password) return null;
  const score = passwordScore(password);
  return (
    <div className="mt-2" data-testid={testid}>
      <div className="flex gap-1">
        {[1, 2, 3, 4].map((i) => (
          <span key={i} className={`h-1.5 flex-1 rounded-full transition-colors ${i <= score ? COLORS[score] : "bg-ayana-line"}`} />
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
        <span className="font-medium text-ayana-text" data-testid={`${testid}-label`}>{LABELS[score]}</span>
        {passwordChecks(password).map((c) => (
          <span key={c.label} className={c.ok ? "text-green-700" : "text-ayana-muted"}>{c.ok ? "✓" : "○"} {c.label}</span>
        ))}
      </div>
    </div>
  );
}
