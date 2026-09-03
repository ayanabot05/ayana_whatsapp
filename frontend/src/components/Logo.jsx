/**
 * Logo.jsx — AYANA new brand mark
 * Uses the detailed A-bridge illustration from /public/ayana_logo.png
 * 
 * Props:
 *   size      - height in px (default 40 for header)
 *   showWord  - false = show only the A-bridge icon part (cropped), true = full logo with AYANA text
 *   className - wrapper classes
 */
import React from "react";

export function Logo({ size = 40, showWord = true, className = "" }) {
  // When showWord=false (header), we want a square icon. 
  // Since your file includes "AYANA" text at bottom, we crop it with object-position
  // For perfect header, later save a second file as public/ayana_mark.png (just the A)
  
  if (!showWord) {
    return (
      <span className={`inline-flex items-center justify-center overflow-hidden ${className}`} 
            style={{ width: size, height: size }}>
        <img
          src="/ayana_logo.png"
          alt="AYANA"
          className="w-full h-full object-contain"
          style={{ 
            objectFit: 'contain',
            // This zooms to show mostly the top 75% (the A-bridge) and hides the big AYANA text
            transform: 'scale(1.35)',
            transformOrigin: 'top center'
          }}
        />
      </span>
    );
  }

  // Full logo with AYANA text - for login, footer, hero
  return (
    <span className={`inline-flex items-center ${className}`}>
      <img
        src="/ayana_logo.png"
        alt="AYANA - Connecting Hearts Across Miles"
        width={size * 2.8}
        height={size * 1.8}
        className="object-contain"
        style={{ height: size * 1.6, width: 'auto', maxWidth: '100%' }}
      />
    </span>
  );
}

export default Logo;