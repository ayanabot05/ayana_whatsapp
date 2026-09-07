// Minimal, dependency-free analytics.
// Buffers events client-side and flushes them to the backend once /api/analytics/event
// exists (built tomorrow). Until then it fails silently — never blocks the UI, never throws.
//
// Usage:
//   import { trackEvent, trackPageView } from "@/lib/analytics";
//   trackPageView("landing");
//   trackEvent("cta_click", { id: "hero-primary" });

const SESSION_KEY = "ayana_session_id";
const API_BASE = process.env.REACT_APP_BACKEND_URL || "";

function getSessionId() {
  try {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id = `s_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
      sessionStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch {
    return "no-session";
  }
}

function send(payload) {
  const body = JSON.stringify({
    ...payload,
    session_id: getSessionId(),
    path: typeof window !== "undefined" ? window.location.pathname : "",
    lang: typeof document !== "undefined" ? document.documentElement.getAttribute("data-lang") : null,
    ts: new Date().toISOString(),
  });

  // Always keep a local trail first — useful while the backend endpoint doesn't exist yet,
  // and as a fallback if the network call fails. Written before the network dispatch so
  // it's captured regardless of which path (sendBeacon vs fetch) is taken below.
  try {
    const key = "ayana_local_events";
    const existing = JSON.parse(localStorage.getItem(key) || "[]");
    existing.push(JSON.parse(body));
    localStorage.setItem(key, JSON.stringify(existing.slice(-200))); // cap growth
  } catch {
    // ignore
  }

  try {
    // Prefer sendBeacon — doesn't block navigation, fires even on page unload
    if (navigator?.sendBeacon && API_BASE) {
      const blob = new Blob([body], { type: "application/json" });
      navigator.sendBeacon(`${API_BASE}/api/analytics/event`, blob);
      return;
    }
    if (API_BASE) {
      fetch(`${API_BASE}/api/analytics/event`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
      }).catch(() => {});
    }
  } catch {
    // Analytics must never break the app. Swallow and move on.
  }
}

export function trackPageView(page) {
  send({ type: "page_view", page });
}

export function trackEvent(name, meta = {}) {
  send({ type: "event", name, meta });
}