import axios from "axios";

// Fall back to local dev server so missing env var never causes cryptic failures.
const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8001";
export const API = `${BACKEND_URL}/api`;

// Use the fetch adapter (axios' default XHR transport intermittently hangs on
// the very first request behind this ingress).
//
// Timeout tuning: production Railway<->Supabase cross-region latency runs
// 3-16s for cold-pool writes (measured post-migration:
//   /payment/checkout 7.4s, /schedules 6.7s, /activation/activate 16.5s).
// A short timeout aborts client-side, error.response is undefined, and
// formatApiError() falls back to the generic 'Something went wrong'
// toast — even though the server already committed the change. So we
// use a generous 30s default and let /activation/activate override per
// request (see Onboarding.js).
export const api = axios.create({ baseURL: API, adapter: "fetch", timeout: 30000, withCredentials: true });

// Auth tokens are sent via HttpOnly, Secure cookies (set by the backend on
// login/register/refresh). withCredentials:true includes them on every request.
// For CSRF we use the double-submit-cookie pattern: the backend also sets a
// readable `csrf_token` cookie; we echo it into the X-CSRF-Token header on every
// state-changing request so validate_csrf_token() passes.
function readCookie(name) {
  const m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
  return m ? decodeURIComponent(m.pop()) : null;
}

const MUTATING = ["post", "put", "patch", "delete"];
api.interceptors.request.use((config) => {
  if (MUTATING.includes((config.method || "").toLowerCase())) {
    const csrf = readCookie("csrf_token");
    if (csrf) config.headers["X-CSRF-Token"] = csrf;
  }
  // axios's fetch adapter incorrectly attaches a real "User-Agent" header,
  // which the XHR adapter never did (browsers block JS from setting it).
  // That turns every request into a CORS preflight your backend doesn't
  // allow (400 Bad Request), which is what breaks mobile Safari logins.
  // Strip it so preflights only ever ask for headers allow_headers permits.
  delete config.headers["User-Agent"];
  delete config.headers["user-agent"];
  return config;
});

let isRefreshing = false;
let failedQueue = [];

const processQueue = (error) => {
  failedQueue.forEach((prom) => (error ? prom.reject(error) : prom.resolve()));
  failedQueue = [];
};

// On a 401, transparently refresh the session using the HttpOnly refresh cookie
// (no tokens in JS/localStorage) and replay the original request once.
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const url = originalRequest?.url || "";
    // Never try to refresh the refresh/login/me calls themselves.
    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest._retry &&
      !/\/auth\/(refresh|login|register|me)/.test(url)
    ) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => failedQueue.push({ resolve, reject }))
          .then(() => api(originalRequest))
          .catch((err) => Promise.reject(err));
      }
      originalRequest._retry = true;
      isRefreshing = true;
      try {
        await api.post("/auth/refresh", {});
        isRefreshing = false;
        processQueue(null);
        return api(originalRequest);
      } catch (refreshError) {
        isRefreshing = false;
        processQueue(refreshError);
        return Promise.reject(refreshError);
      }
    }
    return Promise.reject(error);
  }
);

// Turn a field path like ["body", "habits", "wake_time"] into "Wake time".
function humanizeField(loc) {
  const field = Array.isArray(loc) ? loc[loc.length - 1] : null;
  if (typeof field !== "string") return null;
  return field.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
}

// Rewrite a single raw pydantic error into something a non-technical user
// can act on, instead of dumping the validator's regex/type internals.
function friendlyValidationMessage(e) {
  const label = humanizeField(e?.loc) || "A field";
  const msg = typeof e?.msg === "string" ? e.msg : "";
  if (/match pattern/i.test(msg)) {
    // Covers time-of-day fields (HH:MM) and similar pattern validators.
    return `${label} isn't a valid value — check the format or leave it blank.`;
  }
  if (/field required|missing/i.test(msg) || e?.type === "missing") {
    return `${label} is required.`;
  }
  if (msg) return `${label}: ${msg}`;
  return `${label} isn't valid.`;
}

export function formatApiError(detail) {
  if (detail == null) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const seen = new Set();
    const messages = [];
    for (const e of detail) {
      const friendly = e && typeof e === "object" ? friendlyValidationMessage(e) : String(e);
      if (friendly && !seen.has(friendly)) {
        seen.add(friendly);
        messages.push(friendly);
      }
    }
    return messages.length ? messages.join(" ") : "Please check your input and try again.";
  }
  if (detail && typeof detail === "object") {
    // Shape returned by /payment/checkout when a downgrade doesn't fit
    // current usage: { message, blockers: [...], usage: {...} }.
    if (Array.isArray(detail.blockers) && detail.blockers.length) {
      const intro = typeof detail.message === "string" ? detail.message : "This change needs some cleanup first:";
      return [intro, ...detail.blockers.map((b) => `• ${b}`)].join("\n");
    }
    if (typeof detail.message === "string") return detail.message;
    if (typeof detail.msg === "string") return detail.msg;
  }
  return String(detail);
}

// Wrapper: axios timeouts and network aborts have no error.response, so
// error.response?.data?.detail is undefined and formatApiError returns
// the generic 'Something went wrong'. Callers pass the whole error and
// get a message that actually tells the user what happened, so they
// don't retry a step whose server-side write already succeeded.
export function formatAxiosError(error) {
  if (!error) return "Something went wrong. Please try again.";
  if (error.code === "ECONNABORTED" || /timeout/i.test(error.message || "")) {
    return "The server is taking longer than usual. Your change may have gone through — please refresh the page in a moment before retrying.";
  }
  if (error.response) return formatApiError(error.response.data?.detail);
  if (error.message === "Network Error" || error.code === "ERR_NETWORK") {
    return "Can't reach the server. Please check your internet and try again.";
  }
  return formatApiError(error.response?.data?.detail);
}