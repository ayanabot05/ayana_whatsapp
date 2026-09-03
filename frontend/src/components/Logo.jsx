/**
 * Logo.jsx — Fresh AYANA brand mark.
 *
 * A warm circular emblem (a heart cradled by a rising-sun arc) in a
 * gold -> terracotta gradient, paired with an "AYANA" wordmark in a
 * soft golden gradient. No external image needed — pure SVG so it
 * stays crisp everywhere and matches the warm, no-dark palette.
 *
 * Props:
 *   size        - emblem px size (default 40)
 *   showWord    - render the AYANA wordmark (default true)
 *   className   - wrapper classes
 */
import React from "react";

export function Logo({ size = 40, showWord = true, className = "" }) {
  const gid = React.useId();
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 48 48"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        aria-label="AYANA"
        role="img"
      >
        <defs>
          <linearGradient id={`${gid}-ring`} x1="6" y1="6" x2="42" y2="42" gradientUnits="userSpaceOnUse">
            <stop stopColor="#E9B94B" />
            <stop offset="0.55" stopColor="#D4960A" />
            <stop offset="1" stopColor="#E8590C" />
          </linearGradient>
          <linearGradient id={`${gid}-heart`} x1="16" y1="18" x2="32" y2="34" gradientUnits="userSpaceOnUse">
            <stop stopColor="#FFF6E6" />
            <stop offset="1" stopColor="#FFE7C2" />
          </linearGradient>
        </defs>
        {/* soft filled disc */}
        <circle cx="24" cy="24" r="22" fill={`url(#${gid}-ring)`} />
        {/* inner warm face */}
        <circle cx="24" cy="24" r="17" fill="#FBF3E2" />
        {/* rising-sun arc */}
        <path d="M13 29a11 11 0 0 1 22 0" stroke={`url(#${gid}-ring)`} strokeWidth="2.4" strokeLinecap="round" fill="none" opacity="0.55" />
        {/* heart */}
        <path
          d="M24 32.5c-4.7-3-7.5-5.7-7.5-9.1 0-2.2 1.7-3.9 3.9-3.9 1.5 0 2.8.8 3.6 2 .8-1.2 2.1-2 3.6-2 2.2 0 3.9 1.7 3.9 3.9 0 3.4-2.8 6.1-7.5 9.1z"
          fill="#E8590C"
        />
        {/* little green presence dot (WhatsApp online feel) */}
        <circle cx="35.5" cy="13.5" r="3.6" fill="#25D366" stroke="#FBF3E2" strokeWidth="1.6" />
      </svg>
      {showWord && (
        <span className="font-display text-xl font-extrabold tracking-tight text-gradient-gold">AYANA</span>
      )}
    </span>
  );
}

export default Logo;
