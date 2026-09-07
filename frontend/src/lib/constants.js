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
];
