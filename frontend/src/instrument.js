// Sentry error monitoring · loaded first, before any app code.
// Silently no-ops if REACT_APP_SENTRY_DSN is not set in Vercel env vars —
// safe for local dev without a DSN.
import * as Sentry from "@sentry/react";

const dsn = process.env.REACT_APP_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.REACT_APP_SENTRY_ENVIRONMENT || "production",
    release: process.env.REACT_APP_SENTRY_RELEASE || undefined,

    // Errors only — no APM/tracing, no session replay (keeps free-tier
    // event budget for actual crashes, not perf noise).
    sampleRate: 1.0,

    // GDPR/DPDP: no automatic IP/cookie/request PII. Explicit user email
    // is set post-login via lib/sentryUser.js when the founder wants to
    // correlate an error to a real user.
    sendDefaultPii: false,

    beforeSend(event) {
      // Strip application extras before transmission — event shape stays
      // minimal (message + stack + user + release + env).
      if (event.extra) delete event.extra;
      return event;
    },
  });
}
