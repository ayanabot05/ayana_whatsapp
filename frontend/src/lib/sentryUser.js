// Sentry user context helpers · call after login/logout so Sentry events
// are correlated to the real founder-visible user, not anonymous.
// No-op if Sentry isn't initialized (missing DSN).
import * as Sentry from "@sentry/react";

export function setSentryUser(user) {
  if (!user?.id) return;
  Sentry.setUser({
    id: String(user.id),
    email: user.email,
  });
}

export function clearSentryUser() {
  Sentry.setUser(null);
}
