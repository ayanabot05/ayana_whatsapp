import { useEffect, useState } from "react";
import { COUNTRY_CODES } from "@/lib/constants";

// Combines a country-code dropdown + number input into a single E.164 value.
export function PhoneInput({ value, onChange, testid, placeholder = "98765 43210" }) {
  const [dial, setDial] = useState("+91");
  const [num, setNum] = useState("");

  useEffect(() => {
    const current = `${dial}${num}`;
    if (value === current) return; // already in sync with our own emit — avoid loops
    if (value) {
      const match = [...COUNTRY_CODES]
        .sort((a, b) => b.code.length - a.code.length)
        .find((c) => value.startsWith(c.code));
      if (match) { setDial(match.code); setNum(value.slice(match.code.length).replace(/[^0-9]/g, "")); }
      else setNum(value.replace(/[^0-9]/g, ""));
    } else {
      setNum("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const emit = (d, n) => onChange(`${d}${n.replace(/[^0-9]/g, "")}`);

  return (
    <div className="flex gap-2">
      <select
        value={dial}
        onChange={(e) => { setDial(e.target.value); emit(e.target.value, num); }}
        data-testid={testid ? `${testid}-code` : undefined}
        className="px-2.5 py-3 rounded-xl border border-ayana-line bg-white text-sm focus:outline-none focus:ring-2 focus:ring-ayana-accent/50 focus:border-ayana-accent transition shrink-0 max-w-[7.5rem]"
      >
        {COUNTRY_CODES.map((c) => (
          <option key={c.name} value={c.code}>{c.flag} {c.code}</option>
        ))}
      </select>
      <input
        value={num}
        inputMode="numeric"
        onChange={(e) => { const clean = e.target.value.replace(/[^0-9]/g, ""); setNum(clean); emit(dial, clean); }}
        data-testid={testid}
        placeholder={placeholder}
        className="flex-1 min-w-0 px-4 py-3 rounded-xl border border-ayana-line bg-white focus:outline-none focus:ring-2 focus:ring-ayana-accent/50 focus:border-ayana-accent transition"
      />
    </div>
  );
}
