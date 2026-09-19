# AYANA — WhatsApp Business Templates for Meta Approval (Final)

Twilio's Content API templates are the same thing as WhatsApp Business message templates — Twilio just proxies your submission to Meta. Each entry below is ready to paste into Twilio Console → Content Template Builder for approval.

## Which templates get buttons — quick summary
| # | Template | Buttons? | Payload style | Backend fix needed first? |
|---|---|---|---|---|
| 1 | `opener` | ✅ Yes | Specific (`feeling:good/okay/not_well`) | No — already works as-is |
| 2 | `medicine` | ✅ Yes | Generic (`reminder_done/pending/skip`) | **Yes — done, see note below** |
| 3 | `meal` | ✅ Yes | Generic (`meal_done/pending/skip`) | **Yes — done, see note below** |
| 4 | `mood` | ✅ Yes | Specific (`feeling:good/okay/not_well`) | No — already works as-is |
| 5 | `reengagement` | ❌ No | — | — |
| 6 | `report_ready` | ❌ No | — | — |

**Why opener/mood are safe with specific payloads but medicine/meal aren't:** `opener` maps 1:1 to `morning_wish` — one template, one category, no ambiguity. `mood` covers `how_feeling`/`goodnight`/`love_note`, but all three already share the exact same `feeling:good/okay/not_well` payload scheme in your `BUTTONS` dict — so reusing it template-side introduces no new ambiguity. `medicine` and `meal`, by contrast, each cover 5–6 *different* categories with *different* specific payloads (`done:water` vs `done:medicine` vs `done:bp`) — a template's buttons are fixed at submission time and can't vary per send, so they use generic payloads instead, resolved back to the real category server-side.

**Status: the server-side fix is done.** `_record_reply` in `server.py` now resolves `reminder_*`/`meal_*` generic payloads to the actual category by checking the parent's most recent matching `message_logs` entry — you can submit all 18 templates now.

---

## Meta approval rules to keep in mind
- **Category**: All 18 below are `UTILITY` — transactional/care-coordination, not promotional. Reengagement is borderline; keep its copy neutral (no incentives) or Meta will bounce it to `MARKETING`.
- **Naming**: lowercase + underscores only, unique per language: `ayana_<category>_<lang>`.
- **Variables**: numbered `{{1}}`, `{{2}}`... every variable needs a sample value at submission.
- **Buttons**: max 3 Quick Reply buttons per template, each label max 20 characters.
- **Length**: body max 1024 chars — keep well under (aim <300) for WhatsApp readability.
- **No adjacent variables** with no text between (Meta rejects `{{1}}{{2}}`).
- **Turnaround**: usually minutes to 24h; rejections are common for vague sample values — use realistic names.
- Telugu/Hindi copy below is a first draft — get a native speaker to sanity-check tone before submitting, especially mood/reengagement.

---

## 1. Opener (session starter) — HAS BUTTONS
Sent when the 24h session is closed. This is the daily "how are you feeling" morning touch — not just a reopener.

**Buttons (all 3 languages)**: `Good 😊` → `feeling:good` · `Okay 🙂` → `feeling:okay` · `Not well 😟` → `feeling:not_well`

### ayana_opener_en
- **Category**: UTILITY
- **Body**: `Hi {{1}}! This is AYANA checking in for {{2}}. How are you feeling today?`
- **Sample**: {{1}} = Ramesh, {{2}} = Amma

### ayana_opener_te
- **Body**: `నమస్తే {{1}}! AYANA {{2}} కోసం చెక్-ఇన్ చేస్తోంది. ఈరోజు మీరు ఎలా ఉన్నారు?`
- **Sample**: {{1}} = రమేష్, {{2}} = అమ్మ

### ayana_opener_hi
- **Body**: `नमस्ते {{1}}! AYANA {{2}} के लिए चेक-इन कर रही है। आज आप कैसा महसूस कर रहे हैं?`
- **Sample**: {{1}} = रमेश, {{2}} = अम्मा

---

## 2. Medicine reminder — HAS BUTTONS (covers medicine/water/bp_check/sugar_check/health_check)
**Buttons (all 3 languages, generic payload)**: `Done` → `reminder_done` · `Not yet` → `reminder_pending` · `Skip` → `reminder_skip`

### ayana_medicine_en
- **Body**: `⏰ Time for {{1}}'s {{2}} medicine.`
- **Sample**: {{1}} = Amma, {{2}} = morning BP

### ayana_medicine_te
- **Body**: `⏰ {{1}} యొక్క {{2}} మందు తీసుకునే సమయం అయ్యింది.`
- **Sample**: {{1}} = అమ్మ, {{2}} = ఉదయం BP

### ayana_medicine_hi
- **Body**: `⏰ {{1}} की {{2}} दवा का समय हो गया है।`
- **Sample**: {{1}} = अम्मा, {{2}} = सुबह की BP

---

## 3. Meal / check-in — HAS BUTTONS (covers breakfast/lunch/dinner/afternoon_checkin/tea_check/walk_check)
**Buttons (all 3 languages, generic payload)**: `Yes` → `meal_done` · `Not yet` → `meal_pending` · `Skip` → `meal_skip`

### ayana_meal_en
- **Body**: `🍽️ Just checking — has {{1}} had {{2}} yet?`
- **Sample**: {{1}} = Nanna, {{2}} = lunch

### ayana_meal_te
- **Body**: `🍽️ {{1}} {{2}} తిన్నారా?`
- **Sample**: {{1}} = నాన్న, {{2}} = మధ్యాహ్న భోజనం

### ayana_meal_hi
- **Body**: `🍽️ बस पूछ रही हूँ — क्या {{1}} ने {{2}} खा लिया?`
- **Sample**: {{1}} = नाना, {{2}} = दोपहर का खाना

---

## 4. Mood check-in — HAS BUTTONS (covers how_feeling/goodnight/love_note)
**Buttons (all 3 languages)**: `Good 😊` → `feeling:good` · `Okay 🙂` → `feeling:okay` · `Not well 😟` → `feeling:not_well`

### ayana_mood_en
- **Body**: `💬 How is {{1}} feeling today?`
- **Sample**: {{1}} = Amma

### ayana_mood_te
- **Body**: `💬 ఈరోజు {{1}} ఎలా ఉన్నారు?`
- **Sample**: {{1}} = అమ్మ

### ayana_mood_hi
- **Body**: `💬 आज {{1}} कैसा महसूस कर रहे हैं?`
- **Sample**: {{1}} = अम्मा

---

## 5. Re-engagement (no-reply follow-up) — NO BUTTONS
Kept neutral/informational to stay clear of MARKETING classification.

### ayana_reengagement_en
- **Body**: `Hi {{1}}, I haven't heard back about {{2}}'s check-in today. Everything okay? Reply whenever you can.`
- **Sample**: {{1}} = Priya, {{2}} = Amma

### ayana_reengagement_te
- **Body**: `నమస్తే {{1}}, ఈరోజు {{2}} చెక్-ఇన్ గురించి మీ నుండి రిప్లై రాలేదు. అంతా బాగానే ఉందా? వీలున్నప్పుడు రిప్లై ఇవ్వండి.`
- **Sample**: {{1}} = ప్రియ, {{2}} = అమ్మ

### ayana_reengagement_hi
- **Body**: `नमस्ते {{1}}, आज {{2}} के चेक-इन का जवाब नहीं मिला। सब ठीक तो है? जब समय हो जवाब दें।`
- **Sample**: {{1}} = प्रिया, {{2}} = अम्मा

---

## 6. Report ready — NO BUTTONS
Goes to the child/account owner, not the parent — not part of the tap-reply flow at all.

### ayana_report_ready_en
- **Body**: `📋 {{1}}'s monthly wellness report is ready. Open the AYANA dashboard to view check-ins, mood trends, and medicine adherence.`
- **Sample**: {{1}} = Amma

### ayana_report_ready_te
- **Body**: `📋 {{1}} యొక్క నెలవారీ వెల్‌నెస్ రిపోర్ట్ సిద్ధంగా ఉంది. చెక్-ఇన్‌లు, మూడ్ ట్రెండ్‌లు, మందుల వినియోగం చూడటానికి AYANA డాష్‌బోర్డ్ తెరవండి.`
- **Sample**: {{1}} = అమ్మ

### ayana_report_ready_hi
- **Body**: `📋 {{1}} की मासिक वेलनेस रिपोर्ट तैयार है। चेक-इन, मूड ट्रेंड और दवा अनुपालन देखने के लिए AYANA डैशबोर्ड खोलें।`
- **Sample**: {{1}} = अम्मा

---

## Next steps
1. Submit all 18 via Twilio Console (Content API) — each approved template returns a `ContentSid` (the `HX...` values your `.env` needs). 12 of the 18 (opener, medicine, meal, mood × 3 languages) now include Quick Reply buttons; reengagement and report_ready stay plain-text.
2. Fill in the 12 missing SIDs in `.env.example` (medicine/meal/mood/report_ready × 3 languages) once approved.
3. Expect Meta to sometimes reject `reengagement` on first submission if it reads as promotional — if so, soften further (drop any implied urgency, keep it purely informational).
4. After the first live sends, spot-check `message_logs`/`parent_replies` for any `done:generic`/`pending:generic`/`skip:generic` entries — that fallback firing means the medicine/meal disambiguation lookup didn't find a matching prior send, worth investigating early rather than after a month of data.