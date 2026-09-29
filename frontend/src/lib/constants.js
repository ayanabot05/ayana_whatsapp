export const TIMEZONES = [
  { value: "Asia/Kolkata", label: "India — Kolkata (IST)" },
  { value: "Asia/Dubai", label: "UAE — Dubai (GST)" },
  { value: "Asia/Singapore", label: "Singapore (SGT)" },
  { value: "Europe/London", label: "UK — London (GMT/BST)" },
  { value: "Europe/Berlin", label: "Germany — Berlin (CET)" },
  { value: "America/New_York", label: "USA — New York (ET)" },
  { value: "America/Chicago", label: "USA — Chicago (CT)" },
  { value: "America/Los_Angeles", label: "USA — Los Angeles (PT)" },
  { value: "Australia/Sydney", label: "Australia — Sydney (AEST)" },
  { value: "Asia/Tokyo", label: "Japan — Tokyo (JST)" },
  { value: "America/Toronto", label: "Canada — Toronto (ET)" },
  { value: "Asia/Kathmandu", label: "Nepal — Kathmandu (NPT)" },
];

export const LANG_LABELS = { en: "English", te: "Telugu", hi: "Hindi" };

// Auto-detect the visitor's own timezone from their browser instead of
// hardcoding a single region — customers can be anywhere in India (or the
// world). Falls back to Asia/Kolkata if the browser can't tell us.
export function getBrowserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Kolkata";
  } catch {
    return "Asia/Kolkata";
  }
}

// Make sure the visitor's own timezone is always selectable in the dropdowns,
// even when it isn't one of the curated options above.
const _browserTz = getBrowserTimezone();
if (_browserTz && !TIMEZONES.some((t) => t.value === _browserTz)) {
  TIMEZONES.unshift({ value: _browserTz, label: `Your timezone — ${_browserTz}` });
}

// Common country dial codes (unique labels for dropdown)
export const COUNTRY_CODES = [
  { code: "+91", flag: "🇮🇳", name: "India" },
  { code: "+1", flag: "🇺🇸", name: "USA / Canada" },
  { code: "+44", flag: "🇬🇧", name: "UK" },
  { code: "+971", flag: "🇦🇪", name: "UAE" },
  { code: "+65", flag: "🇸🇬", name: "Singapore" },
  { code: "+61", flag: "🇦🇺", name: "Australia" },
  { code: "+49", flag: "🇩🇪", name: "Germany" },
  { code: "+33", flag: "🇫🇷", name: "France" },
  { code: "+64", flag: "🇳🇿", name: "New Zealand" },
  { code: "+977", flag: "🇳🇵", name: "Nepal" },
  { code: "+60", flag: "🇲🇾", name: "Malaysia" },
  { code: "+974", flag: "🇶🇦", name: "Qatar" },
  { code: "+966", flag: "🇸🇦", name: "Saudi Arabia" },
  { code: "+31", flag: "🇳🇱", name: "Netherlands" },
  { code: "+39", flag: "🇮🇹", name: "Italy" },
  { code: "+41", flag: "🇨🇭", name: "Switzerland" },
  { code: "+32", flag: "🇧🇪", name: "Belgium" },
  { code: "+46", flag: "🇸🇪", name: "Sweden" },
  { code: "+82", flag: "🇰🇷", name: "South Korea" },
  { code: "+81", flag: "🇯🇵", name: "Japan" },
  { code: "+62", flag: "🇮🇩", name: "Indonesia" },
  { code: "+63", flag: "🇵🇭", name: "Philippines" },
  { code: "+66", flag: "🇹🇭", name: "Thailand" },
  { code: "+55", flag: "🇧🇷", name: "Brazil" },
  { code: "+52", flag: "🇲🇽", name: "Mexico" },
  { code: "+353", flag: "🇮🇪", name: "Ireland" },
  { code: "+351", flag: "🇵🇹", name: "Portugal" },
  { code: "+34", flag: "🇪🇸", name: "Spain" },
  { code: "+47", flag: "🇳🇴", name: "Norway" },
  { code: "+45", flag: "🇩🇰", name: "Denmark" },
  { code: "+358", flag: "🇫🇮", name: "Finland" },
  { code: "+48", flag: "🇵🇱", name: "Poland" },
  { code: "+90", flag: "🇹🇷", name: "Turkey" },
  { code: "+7", flag: "🇷🇺", name: "Russia" },
  { code: "+86", flag: "🇨🇳", name: "China" },
  { code: "+27", flag: "🇿🇦", name: "South Africa" },
  { code: "+234", flag: "🇳🇬", name: "Nigeria" },
  { code: "+254", flag: "🇰🇪", name: "Kenya" },
  { code: "+20", flag: "🇪🇬", name: "Egypt" },
  { code: "+94", flag: "🇱🇰", name: "Sri Lanka" },
  { code: "+92", flag: "🇵🇰", name: "Pakistan" },
  { code: "+880", flag: "🇧🇩", name: "Bangladesh" },
];
