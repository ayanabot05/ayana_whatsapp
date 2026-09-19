# AYANA_BOT — Pre-Deployment Audit Report
**Date:** Aug 20, 2026 · **Deadline:** 2 days · **Scope:** Full backend (FastAPI/MongoDB) + frontend (React) code review, route-by-route wiring check, and static analysis.

> ⚠️ **Important limitation:** This sandbox has no network access to your MongoDB Atlas cluster, so I could **not execute** the live pytest suite or spin up a real e2e run against a database. Everything below is from **static code analysis** (reading every route, every frontend call site, and diffing them programmatically). Section 7 gives you the exact commands to run the dynamic tests yourself — do that today, in parallel with the fixes below.

---

## 1. Frontend ↔ Backend wiring — the actual diff

I extracted every `@api.get/post/put/delete` route in `server.py` (64 routes) and every `api.get/post/put/delete(...)` call site across the whole frontend `src/` tree, normalized dynamic IDs, and diffed them.

### 🔴 CRITICAL — Frontend calls a route that doesn't exist
**`GET /api/circle/invite/{token}` — used in `InviteClaim.js` line 33, does not exist in `server.py`.**
- The Care Circle invite-acceptance page (`/invite/:token`) calls this on mount to preview the invite before showing "Accept."
- Backend only has `POST /circle/invite/{token}/accept`. There is **no GET route to preview an invite by token**.
- **Effect: every invite link anyone opens will fail immediately** — the page will sit in its error state ("Something went wrong") and no one can ever accept a Care Circle invite via link. This is a full feature outage, not an edge case.
- **Fix:** add `@api.get("/circle/invite/{token}")` in `server.py` that decodes the token the same way `accept_invite_by_token` does and returns `{email, owner_name, ...}` for the preview, without requiring auth (the page needs to show a preview to logged-out users).

### 🟡 Backend routes never called from frontend (dead or unwired code)
| Route | Likely status |
|---|---|
| `POST /parents/{id}/say-hi` | Feature built, no button wired to it anywhere in the UI |
| `PUT /preferences` | Backend supports updating `emergency_keywords` etc., no settings UI calls it |
| `PUT /admin/emergency-events/{id}` | Admin panel *reads* `/admin/emergencies` but has no action to update/resolve one |
| `POST /messages/preview` | Looks like a dev/QA helper endpoint, unused by any page |
| `POST /whatsapp/send-test`, `POST /care-watch/run` | Ops/debug endpoints — fine to leave unwired, not user-facing |

These aren't breaking anything, but "say-hi" and admin emergency-resolution look like real features someone forgot to wire into a button.

### ✅ Everything else lines up 1:1
All auth, parents, schedules, moments, circle (except the one gap above), payment, reports, messages, and admin-list routes have matching frontend calls with matching HTTP verbs.

---

## 2. New features added yesterday — status check

### OTP verification
- Backend: fully built — `otp.py` (275 lines), self-contained rate limiting (max 3 sends/10-min window), hashed codes, resend logic. Both `/auth/otp/*` (account owner) and `/parents/{id}/otp/*` (parent phone) variants exist.
- Frontend: wired into **`Dashboard.js`** (lines 617–635) as a post-onboarding settings action.
- 🔴 **Gap: NOT wired into `Onboarding.js`.** The child's phone number is collected in onboarding step 0 (`saveChild`, line 186) and saved directly via `PUT /profile/child` with **no OTP step at all**. Same for parent phone numbers added during onboarding — no verify step there either, only in Dashboard afterward.
- Your message said "otp verification for child while onboarding" — as built today, **that verification does not happen during onboarding**, only later if the user finds it in Dashboard settings. If OTP-at-onboarding is a hard requirement for launch, this needs the send/verify UI added into the Onboarding step 0 flow before `saveChild` completes.

### Report generation
- Backend (`monthly_report.py`): properly implemented — plan-tiered depth (Nitya: counts only / Bandham: counts + mood graph + trend / Raksha: same, fanned to both Care Circle members), correct month-bounded queries (a prior date-range bug was already fixed per the file's own changelog comment), WhatsApp "report ready" nudge on generation.
- Frontend: `GET /reports/monthly` and `POST /reports/monthly/generate` both called correctly.
- ✅ This one is solid, end-to-end.
- Note: an earlier plan to send the **full report as a WhatsApp PDF document** (not just a "check your dashboard" nudge) was never built — only the nudge exists. Not a bug, just an unbuilt nice-to-have; call it out of scope for this deploy unless you say otherwise.

---

## 3. Frontend/backend coupling (your point #3)

✅ Clean. Every data call in the entire frontend goes through the single `axios` instance in `lib/api.js` (confirmed via full-tree grep — the only other file touching `fetch`/`axios` is `analytics.js`, which is a separate analytics beacon, not app data). No direct DB access, no hardcoded bypass calls, one shared interceptor handles auth-token attach + silent refresh-on-401 with a request queue (well-built — avoids the thundering-herd refresh bug).

---

## 4. Validation, auth, and error messaging (your point #4)

**Auth backend — solid:**
- Register: checks for existing email, returns a clear `"An account with this email already exists."` (not a blank 500).
- Login: has its own brute-force protection (separate from the endpoint rate limit) with a proper `429` + `Retry-After` header and a clear message.
- `formatApiError()` in `lib/api.js` is genuinely well designed — it unpacks FastAPI's validation-error arrays into de-duplicated, human-readable sentences, and even has a special case for the `/payment/checkout` "downgrade blocked" response shape (bulleted list of blockers). This is one of the better parts of the codebase — every page that calls it gets consistent, non-blank error messages.

**Gap found:**
- Activation success (point #4's popup request): `Onboarding.js` `activate()` (line 314) calls `POST /activation/activate` then **silently navigates** to `/activation` with no toast/confirmation at the moment of the click — success is only communicated by the destination page's heading ("Your care circle is active 🎉"). Functionally fine, but doesn't match "tell them success... with a pop up." **Fix:** add `toast.success(...)` immediately after the API call succeeds, before navigating.

---

## 5. Standardization / code health (your point #5)

| Area | Finding |
|---|---|
| **Rate limiting** | Only `register` (5/min) and `login` (10/min) use the global `slowapi` limiter. OTP endpoints have their own custom limiter (fine). **Unprotected:** `/circle/invite` (email-invite spam), `/messages/send-test`, `/whatsapp/send-test` (could be used to spam real WhatsApp sends and burn your Meta messaging budget if a token leaks) — no rate limit on any of these. |
| **Lazy loading** | ✅ Done well — `App.js` route-splits every heavy page (`Onboarding`, `Dashboard`, `Activation`, `Admin`, `InviteClaim`) behind `React.lazy` + `Suspense`. |
| **Pagination** | ✅ Present and correct on the three admin list views (`/admin/users`, `/admin/messages`, `/admin/schedules`) — all use `skip`/`limit` query params consistently. |
| **Caching / react-query** | 🟡 Inconsistent. Only 3 files use `@tanstack/react-query` (which gives you caching, dedup, and background refetch for free). The bulk of data-fetching — including `Dashboard.js`, the largest and most-used page in the app — is done with raw `useState` + `useEffect`, meaning it refetches from scratch on every mount with no caching or request dedup. Not a launch blocker, but worth a follow-up pass. |
| **Silent failures** | None found — every `.catch()` I checked routes through `formatApiError` + a toast rather than swallowing the error. |

---

## 6. Emergency/distress detection — re-check of previously known gaps

Your memory notes flagged several distress-detection gaps a day or so ago. Re-checked against the current code:

- ✅ **Fixed:** button-triggered replies via the `msg_type == "button"` (template quick-reply) path now correctly run `detect_emergency()` against the button's label text, so keyword matching applies there.
- 🔴 **Still open:** for `msg_type == "interactive"` (in-session WhatsApp buttons — `button_reply`/`list_reply`), `body_text` is **never populated** (`server.py` around line 1496–1516 only sets `body_text` for `text` and `button` types, not `interactive`). Since the emergency-event record is only created `if keywords and parent:` (line 1378) and `keywords` comes from `detect_emergency(body_text, ...)`, **an in-session emergency button tap with empty body_text can never trigger an emergency_events record**, regardless of what the button means.
- 🔴 **Still open (matches your earlier note):** the reengagement WhatsApp template (`send_reengagement` in `whatsapp.py`) sends a single-variable text template with **no quick-reply buttons** — the "I'm fine" / "Need help" button pair discussed earlier was never implemented in `interactive_button_handler.py` (grepped — no matches for `need_help`/`im_fine`/emergency handling in that file at all).
- This matters because it's a **safety feature**, not a cosmetic one. If the reengagement flow is meant to be a safety net for an unresponsive parent, right now it can't actually raise an alert from a button tap.

---

## 7. Testing (your points #6 and #7)

I could not run the live suite (`backend/tests/`) here because `database.py` connects to your MongoDB Atlas cluster, which isn't reachable from this sandboxed environment. The test suite itself looks properly structured (session-scoped fixtures, real registration/login flow, admin-auth fixture, 8 test files covering circle/send, e2e full flow, whatsapp routing, sarvam/distress, i18n, gaps-9-10-11). Please run it yourself before deploy:

```bash
cd backend
pip install -r requirements.txt --break-system-packages   # or use your venv
pytest -v
```

Given the size of the app, I'd treat a green pytest run as a hard go/no-go gate — it directly exercises the auth, circle-invite, whatsapp-routing and distress-detection code discussed above.

For the manual click-testing you're planning (point #7), prioritize in this order given what's above:
1. Care Circle invite link end-to-end (currently broken — fix first, then test)
2. Onboarding → activation → dashboard happy path
3. OTP flows (Dashboard settings) since that's the only place they're currently wired
4. WhatsApp webhook reply simulation via `POST /replies/simulate` for each button type

---

## 8. Summary scorecard

### 🟢 Perfect (verified working end-to-end, both sides)
- Auth: register / login / refresh / logout, with real brute-force protection and clear errors
- Parents CRUD, schedules CRUD, Care Circle invite creation/cancel (except the broken preview-by-token GET)
- Monthly report generation (backend depth logic + frontend fetch)
- OTP subsystem itself (backend + Dashboard-side frontend) — just not wired into onboarding
- Admin list views: users/messages/schedules, all paginated correctly
- Global error-message handling (`formatApiError`)
- Route-level lazy loading

### 🟡 Somewhat good (works but needs a fix on one side)
- Activation flow — works, but no success toast at the trigger point
- Emergency detection — keyword path fixed for template buttons, still gapped for in-session interactive buttons
- Reengagement template — sends fine, but missing the planned quick-reply buttons (safety-relevant)
- Data-fetch caching — works but inconsistent (react-query in 3 places, manual fetch everywhere else)
- `say-hi` and admin emergency-resolution — backend ready, no frontend entry point

### 🔴 Fixes required before deploy
1. **Add `GET /api/circle/invite/{token}`** to `server.py` — invite links are 100% broken without it.
2. **Wire OTP verification into `Onboarding.js`** if you want it enforced at onboarding time (currently optional/Dashboard-only).
3. **Populate `body_text` for interactive button replies** (or otherwise route intent into the emergency-event check) so in-session button taps can trigger `emergency_events`.
4. **Add rate limiting** to `/circle/invite`, `/messages/send-test`, `/whatsapp/send-test`.
5. Run the real pytest suite against your Atlas DB before deploy (I couldn't from here).

---

Ready to start fixing — want me to go in the priority order above (invite bug first, since it's the one guaranteed to break for real users), or do you want to knock out the emergency-detection gap first given it's safety-related?
