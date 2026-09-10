import { Link } from "react-router-dom";
import { Check, Heart } from "lucide-react";
import { PhoneMockup } from "@/components/PhoneMockup";
import { Logo } from "@/components/Logo";

/**
 * AuthBrandPanel — the left brand panel used on Login and Signup pages.
 * Single shared component so both pages stay in sync automatically.
 *
 * Warm amber-to-deep-saffron gradient with an emotional quote area.
 * The colour palette is softer and more inviting than a generic tech gradient.
 *
 * showPhone: renders the reusable PhoneMockup (same component as the
 * Landing hero) instead of the bullet list — used on Signup, where seeing
 * the actual product in action helps more than another bullet list.
 */
export function AuthBrandPanel({ headline, subtext, bullets = [], footer, showPhone = false, emotionalQuote }) {
  return (
    <div
      className="hidden lg:flex flex-col justify-between p-12 text-white relative overflow-hidden"
      style={{ background: "linear-gradient(160deg, #D4960A 0%, #C07A08 40%, #8B5E0A 100%)" }}
    >
      {/* Grain and warm glow decorations */}
      <div className="grain-texture absolute inset-0 opacity-10" aria-hidden="true" />
      <div className="absolute -top-20 -right-20 w-96 h-96 rounded-full blur-3xl" style={{ background: "rgba(255,220,120,0.22)" }} />
      <div className="absolute bottom-0 left-0 w-72 h-72 rounded-full blur-3xl" style={{ background: "rgba(139,94,10,0.25)" }} />
      {/* Subtle warm accent orb */}
      <div className="absolute top-1/2 left-1/4 w-48 h-48 rounded-full blur-3xl" style={{ background: "rgba(255,180,50,0.12)" }} />

      {/* Logo */}
      <Link to="/" className="relative flex items-center gap-3">
        <Logo size={38} showWord={false} />
        <span className="font-display text-xl font-bold text-white">AYANA</span>
      </Link>

      {/* Main content */}
      <div className="relative max-w-md">
        <h2 className="font-display text-4xl font-bold leading-tight text-white">{headline}</h2>
        {subtext && <p className="mt-5 text-white/85 text-lg leading-relaxed">{subtext}</p>}

        {showPhone ? (
          <div className="mt-8 scale-[0.82] origin-left">
            <PhoneMockup />
          </div>
        ) : (
          bullets.length > 0 && (
            <ul className="mt-8 space-y-3 text-white/90">
              {bullets.map((txt, i) => (
                <li key={txt} className="flex items-center gap-3">
                  <span
                    className="w-6 h-6 rounded-full flex items-center justify-center text-xs shrink-0"
                    style={{
                      background: `rgba(255,255,255,0.18)`,
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

        {/* Emotional quote — optional callout for extra warmth */}
        {emotionalQuote && (
          <div className="mt-10 bg-white/10 backdrop-blur-sm rounded-2xl px-6 py-5 border border-white/15">
            <div className="flex items-start gap-3">
              <Heart className="w-5 h-5 text-amber-200 shrink-0 mt-0.5" fill="currentColor" />
              <p className="font-serif text-white/90 text-base italic leading-relaxed">
                {emotionalQuote}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      {footer && <p className="relative text-sm text-white/55 leading-relaxed">{footer}</p>}
    </div>
  );
}
