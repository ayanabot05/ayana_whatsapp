import { useState } from "react";
import { Check, Sparkles, ShieldCheck } from "lucide-react";

export function PricingCards({ plans = [], currencies = [], selectedPlan, onSelect, compact = false }) {
  const [currency, setCurrency] = useState(() => {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      return tz === "Asia/Kolkata" || tz === "Asia/Calcutta" ? "INR" : "USD";
    } catch { return "USD"; }
  });
  const [billing, setBilling] = useState("month");
  const cur = currencies.find((c) => c.code === currency) || { symbol: "$", code: "USD" };

  // For integers (INR) don't show decimals, for floats show 2dp
  const fmtNum = (n) => {
    if (n == null) return "";
    return Number.isInteger(n) ? `${n}` : n.toFixed(2);
  };

  const getMonthlyPrice = (price) => {
    if (!price) return null;
    return billing === "year" ? price.year / 12 : price.month;
  };

  const getPriceDisplay = (price) => {
    if (!price) return { big: "", sub: null, crossed: null, savings: null };
    if (billing === "month") {
      return {
        big: `${cur.symbol}${fmtNum(price.month)}`,
        label: "/mo",
        sub: null,
        crossed: null,
        savings: null,
      };
    }
    // Annual: show per-month, crossed monthly, savings callout
    const perMonth = price.year / 12;
    const saved = price.month * 2; // 2 months free
    return {
      big: `${cur.symbol}${fmtNum(Math.floor(perMonth * 100) / 100)}`,
      label: "/mo",
      crossed: `${cur.symbol}${fmtNum(price.month)}`,
      sub: `${cur.symbol}${fmtNum(price.year)}/year · ${cur.symbol}${fmtNum(price.month)} × 10 months`,
      savings: `Save ${cur.symbol}${fmtNum(Math.round(saved))} (2 months free)`,
    };
  };

  return (
    <div>
      {/* Billing toggle + currency */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 mb-6">
        <div className="inline-flex rounded-full border border-ayana-line bg-white p-1" data-testid="billing-toggle">
          {[["month", "Monthly"], ["year", "Yearly 🎉 save 2 months"]].map(([k, label]) => (
            <button key={k} onClick={() => setBilling(k)} data-testid={`billing-${k}`}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${billing === k ? "bg-ayana-gold text-white" : "text-ayana-secondary hover:text-ayana-text"}`}>
              {label}
            </button>
          ))}
        </div>
        <select value={currency} onChange={(e) => setCurrency(e.target.value)} data-testid="currency-select"
          className="px-3 py-2 rounded-full border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-gold/40">
          {currencies.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}
        </select>
      </div>

      <div className="grid md:grid-cols-3 gap-5">
        {plans.map((p) => {
          const active = selectedPlan === p.id;
          const priceData = p.price[cur.code];
          const display = getPriceDisplay(priceData);
          return (
            <div key={p.id} data-testid={`plan-${p.id}`}
              className={`relative rounded-2xl border p-6 transition-all duration-300 flex flex-col ${
                p.highlight
                  ? "border-ayana-gold bg-white shadow-xl ring-1 ring-ayana-gold/30"
                  : "border-ayana-line bg-white shadow-sm"
              } ${active ? "ring-2 ring-ayana-accent" : ""}`}>

              {/* Most loved badge */}
              {p.highlight && (
                <span className="absolute -top-3 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 text-xs font-semibold px-4 py-1.5 rounded-full bg-ayana-gold text-white whitespace-nowrap shadow">
                  <Sparkles className="w-3 h-3" /> Most loved
                </span>
              )}

              {/* Free trial badge */}
              <div className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1 mb-4 w-fit">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                7 days free · no card needed
              </div>

              <h3 className="font-display text-xl font-semibold text-ayana-text">{p.name}</h3>
              <p className="text-sm text-ayana-muted mt-0.5">{p.tagline}</p>

              {/* Price block */}
              <div className="mt-5">
                <div className="flex items-end gap-2">
                  <span className="font-display text-4xl font-black text-ayana-text">{display.big}</span>
                  {display.crossed && (
                    <span className="text-ayana-muted text-base line-through mb-1">{display.crossed}</span>
                  )}
                  <span className="text-ayana-muted text-sm mb-1.5">{display.label}</span>
                </div>
                {display.sub && (
                  <p className="text-xs text-ayana-muted mt-1">{display.sub}</p>
                )}
                {display.savings && (
                  <p className="text-xs font-semibold text-emerald-600 mt-1">🎉 {display.savings}</p>
                )}
              </div>

              {/* Features */}
              <ul className="mt-5 space-y-2.5 flex-1">
                {p.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-sm text-ayana-secondary">
                    <Check className="w-4 h-4 text-ayana-gold shrink-0 mt-0.5" strokeWidth={2.5} /> {f}
                  </li>
                ))}
              </ul>

              {/* CTA */}
              {onSelect ? (
                <button onClick={() => onSelect(p.id, billing)} data-testid={`select-plan-${p.id}`}
                  className={`mt-6 w-full py-3 rounded-full font-semibold transition-colors text-sm ${
                    p.highlight
                      ? "bg-ayana-gold text-white hover:bg-ayana-gold/90"
                      : "bg-ayana-primary text-white hover:bg-ayana-primary/90"
                  }`}>
                  {active ? "Selected ✓" : `Start free · ${p.name.replace("AYANA ", "")}`}
                </button>
              ) : null}
            </div>
          );
        })}
      </div>

      {!compact && (
        <div className="mt-6 text-center space-y-1">
          <p className="text-xs text-ayana-muted flex items-center justify-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-ayana-gold" />
            Cancel anytime · 14-day money-back guarantee · No hidden costs
          </p>
        </div>
      )}
    </div>
  );
}
