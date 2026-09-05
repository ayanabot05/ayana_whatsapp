import { useState } from "react";
import { Check, Sparkles } from "lucide-react";

export function PricingCards({ plans = [], currencies = [], selectedPlan, onSelect, compact = false }) {
  const [currency, setCurrency] = useState(() => {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      return tz === "Asia/Kolkata" || tz === "Asia/Calcutta" ? "INR" : "USD";
    } catch { return "USD"; }
  });
  const [billing, setBilling] = useState("month");
  const cur = currencies.find((c) => c.code === currency) || { symbol: "$", code: "USD" };

  const fmt = (n) => {
    if (n == null) return "";
    const val = billing === "year" ? n.year : n.month;
    return `${cur.symbol}${val}`;
  };

  return (
    <div>
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 mb-6">
        <div className="inline-flex rounded-full border border-ayana-line bg-white p-1" data-testid="billing-toggle">
          {[["month", "Monthly"], ["year", "Yearly · save 2 months"]].map(([k, label]) => (
            <button key={k} onClick={() => setBilling(k)} data-testid={`billing-${k}`}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${billing === k ? "bg-ayana-primary text-white" : "text-ayana-secondary hover:text-ayana-text"}`}>{label}</button>
          ))}
        </div>
        <select value={currency} onChange={(e) => setCurrency(e.target.value)} data-testid="currency-select"
          className="px-3 py-2 rounded-full border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-accent/50">
          {currencies.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
        </select>
      </div>

      <div className="grid md:grid-cols-2 gap-5">
        {plans.map((p) => {
          const active = selectedPlan === p.id;
          return (
            <div key={p.id} data-testid={`plan-${p.id}`}
              className={`relative rounded-2xl border p-6 transition-all duration-300 ${p.highlight ? "border-ayana-accent bg-white shadow-lg" : "border-ayana-line bg-white"} ${active ? "ring-2 ring-ayana-accent" : ""}`}>
              {p.highlight && (
                <span className="absolute -top-3 left-6 inline-flex items-center gap-1 text-xs font-medium px-3 py-1 rounded-full bg-ayana-accent text-white"><Sparkles className="w-3 h-3" /> Most loved</span>
              )}
              <h3 className="font-display text-xl font-semibold text-ayana-text">{p.name}</h3>
              <p className="text-sm text-ayana-muted">{p.tagline}</p>
              <div className="mt-4 flex items-end gap-1">
                <span className="font-display text-4xl font-bold text-gradient-gold">{fmt(p.price[cur.code])}</span>
                <span className="text-ayana-muted text-sm mb-1.5">/{billing === "year" ? "year" : "mo"}</span>
              </div>
              <ul className="mt-5 space-y-2.5">
                {p.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm text-ayana-secondary"><Check className="w-4 h-4 text-ayana-primary shrink-0 mt-0.5" /> {f}</li>
                ))}
              </ul>
              {onSelect && (
                <button onClick={() => onSelect(p.id, billing)} data-testid={`select-plan-${p.id}`}
                  className={`mt-6 w-full py-3 rounded-full font-medium transition-colors ${p.highlight ? "bg-ayana-accent text-white hover:bg-ayana-accent-hover" : "bg-ayana-primary text-white hover:bg-ayana-primary-hover"}`}>
                  {active ? "Selected ✓" : `Choose ${p.name.replace("AYANA ", "")}`}
                </button>
              )}
            </div>
          );
        })}
      </div>
      {!compact && (
        <p className="mt-5 text-center text-xs text-ayana-muted">{"Payments are disabled during testing. You'll continue on a free trial. Cancel anytime."}</p>
      )}
    </div>
  );
}
