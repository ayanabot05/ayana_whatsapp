import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { PhoneMockup } from "@/components/PhoneMockup";
import { Logo } from "@/components/Logo";

/**
 * AuthBrandPanel — the left brand panel used on Login and Signup pages.
 * Single shared component so both pages stay in sync automatically.
 *
 * Restyled to match the warm gold/saffron gradient from the Landing page
 * final CTA section, replacing the previous dark emerald look.
 *
 * showPhone: renders the reusable PhoneMockup (same component as the
 * Landing hero) instead of the bullet list — used on Signup, where seeing
 * the actual product in action helps more than another bullet list.
 */
export function AuthBrandPanel({ headline, subtext, bullets = [], footer, showPhone = false }) {
  return (
    <div
      className="hidden lg:flex flex-col justify-between p-12 text-white relative overflow-hidden"
      style={{ background: "linear-gradient(160deg, #E8B84B 0%, #D4960A 45%, #E8590C 100%)" }}
    >
      {/* Grain and warm glow decorations */}
      <div className="grain-texture absolute inset-0 opacity-10" aria-hidden="true" />
      <div className="absolute -top-16 -right-16 w-80 h-80 rounded-full blur-3xl" style={{ background: "rgba(255,255,255,0.18)" }} />
      <div className="absolute bottom-0 left-0 w-60 h-60 rounded-full blur-3xl" style={{ background: "rgba(0,0,0,0.1)" }} />

      {/* Logo */}
      <Link to="/" className="relative flex items-center gap-3">
        <Logo size={38} showWord={false} />
        <span className="font-display text-xl font-bold text-white">AYANA</span>
      </Link>

      {/* Main content */}
      <div className="relative max-w-md">
        <h2 className="font-display text-4xl font-bold leading-tight text-white">{headline}</h2>
        {subtext && <p className="mt-5 text-white/80 text-lg">{subtext}</p>}

        {showPhone ? (
          <div className="mt-8 scale-[0.82] origin-left">
            <PhoneMockup />
          </div>
        ) : (
          bullets.length > 0 && (
            <ul className="mt-8 space-y-3 text-white/85">
              {bullets.map((txt, i) => (
                <li key={txt} className="flex items-center gap-3">
                  <span
                    className="w-6 h-6 rounded-full flex items-center justify-center text-xs shrink-0"
                    style={{
                      background: [`rgba(255,255,255,0.22)`, `rgba(255,255,255,0.18)`, `rgba(255,255,255,0.22)`][i % 3],
                      color: '#fff',
                    }}
                  >
                    <Check className="w-3.5 h-3.5" />
                  </span>
                  {txt}
                </li>
              ))}
            </ul>
          )
        )}
      </div>

      {/* Footer */}
      {footer && <p className="relative text-sm text-white/50">{footer}</p>}
    </div>
  );
}
