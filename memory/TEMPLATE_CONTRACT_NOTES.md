# User-supplied template contracts — planning snapshot 2026-09-20

Source: founder's latest message. These are supplied definitions, NOT a live Meta verification. Exact website URL configuration (static vs dynamic/base/suffix), quick-reply payload rules, active category and approval must be inspected before live sends. User says they have approved templates, but pasted inventory also contains 'Ready to submit'. Do not relabel unsupported content or bypass country restrictions.

## Existing definitions

Founder reposted the opener/mood/meal/medicine/reengagement/report, office/market/shopping/temple/outing safety, and first/main child + first parent warning templates matching `docs/meta_approved_templates.txt`. That file can be used for exact prior text. Office/market/temple/outing use parent name; shopping uses parent name and custom location label; main child warning uses parent name and missed count.

Generic `ayana_outing_return_*` is suitable neutral safe-return wording for locations not named in dedicated templates, including mosque/church. Do not use temple/darshan text for non-temple destinations. 'Shopping done' or 'Darshan done' is not necessarily confirmation of arriving home; keep reply semantics accurate.

## New supplied contracts

### Text/button reply notification — four body variables

Order: parent display name, exact check-in description, reply text, date/time with timezone.

- `ayana_parent_reply_en` / language `en`:
  AYANA care update: {{1}} replied to the {{2}} check-in.
  Their reply: {{3}}
  Received at: {{4}}
  You can view this update and recent check-ins in your AYANA dashboard.
  Buttons: Website 'View reply'; Quick reply 'Send full reply'.
- `ayana_parent_reply_te` / `te`:
  AYANA సమాచారం: {{1}} {{2}} చెక్-ఇన్‌కు సమాధానం ఇచ్చారు.
  వారి సమాధానం: {{3}}
  అందిన సమయం: {{4}}
  ఈ సమాధానాన్ని, ఇటీవలి చెక్-ఇన్‌లను మీ AYANA డ్యాష్‌బోర్డ్‌లో చూడవచ్చు.
  Buttons: Website 'సమాధానం చూడండి'; Quick reply 'పూర్తి సమాధానం'.
- `ayana_parent_reply_hi` / `hi`:
  AYANA अपडेट: {{1}} ने {{2}} चेक-इन का जवाब दिया है।
  उनका जवाब: {{3}}
  जवाब मिलने का समय: {{4}}
  यह जवाब और हाल के चेक-इन अपने AYANA डैशबोर्ड में देखें।
  Buttons: Website 'जवाब देखें'; Quick reply 'पूरा जवाब भेजें'.

### Voice-note notification — three body variables

Order: parent display name, exact check-in description, date/time with timezone.

- `ayana_parent_voice_en` / `en`:
  AYANA care update: {{1}} sent a voice note in response to the {{2}} check-in.
  Received at: {{3}}
  Listen in your AYANA dashboard, or tap “Send voice note” to request the audio here.
  Buttons: Website 'Open dashboard'; Quick reply 'Send voice note'.
- `ayana_parent_voice_te` / `te`:
  AYANA సమాచారం: {{1}} {{2}} చెక్-ఇన్‌కు వాయిస్ మెసేజ్ పంపారు.
  అందిన సమయం: {{3}}
  మీ AYANA డ్యాష్‌బోర్డ్‌లో వినండి. ఇక్కడ వినాలంటే “వాయిస్ పంపండి” బటన్‌ను నొక్కండి.
  Buttons: Website 'డ్యాష్‌బోర్డ్ చూడండి'; Quick reply 'వాయిస్ పంపండి'.
- `ayana_parent_voice_hi` / `hi`:
  AYANA अपडेट: {{1}} ने {{2}} चेक-इन के जवाब में एक वॉइस मैसेज भेजा है।
  मिलने का समय: {{3}}
  अपने AYANA डैशबोर्ड में सुनें, या यहाँ ऑडियो पाने के लिए “वॉइस भेजें” बटन दबाएँ।
  Buttons: Website 'डैशबोर्ड खोलें'; Quick reply 'वॉइस भेजें'.

### Child welcome after verified/consented onboarding — one body variable

Order: child's first name. Once at appropriate verification/consent event, NOT every login. Do not reuse this wording for phone-change acknowledgment or sibling invitation since those are different events.

- `ayana_child_welcome_en` / `en`:
  Hi {{1}}, your email is verified and your AYANA account is ready.
  Add your parent's details and choose their check-in times in your dashboard. AYANA will use your selected WhatsApp number for care updates.
  Buttons: Website 'Open dashboard'; Quick reply 'Enable updates'.
- `ayana_child_welcome_te` / `te`:
  నమస్తే {{1}}, మీ ఇమెయిల్ ధృవీకరణ పూర్తయింది. మీ AYANA ఖాతా సిద్ధంగా ఉంది.
  డ్యాష్‌బోర్డ్‌లో మీ తల్లిదండ్రుల వివరాలు, చెక్-ఇన్ సమయాలను నమోదు చేయండి. మీరు ఎంచుకున్న WhatsApp నంబర్‌కు AYANA సంరక్షణ సమాచారాన్ని పంపుతుంది.
  Buttons: Website 'డ్యాష్‌బోర్డ్ చూడండి'; Quick reply 'అప్‌డేట్లు కావాలి'.
- `ayana_child_welcome_hi` / `hi`:
  नमस्ते {{1}}, आपका ईमेल सत्यापित हो गया है और आपका AYANA खाता तैयार है।
  डैशबोर्ड में अपने माता-पिता की जानकारी और चेक-इन का समय जोड़ें। AYANA आपके चुने हुए WhatsApp नंबर पर देखभाल से जुड़े अपडेट भेजेगा।
  Buttons: Website 'डैशबोर्ड खोलें'; Quick reply 'अपडेट शुरू करें'.

## Constraints to preserve

- Raw audio can be sent within the child's service window. Outside it, send approved voice notification; tapping its quick reply opens a service window and must deliver the specific authorized audio. Website clicks do not open it.
- Business templates do not themselves open a free-form 24-hour service window. The source's example asserting that is incorrect.
- Existing child-button code exists in `services/notifications.py`; the pasted note saying it still must be implemented is not proof it is absent. Verify and harden actual paths, including failures and duplicate clicks.
- New links should open unified Check-ins and focus exact parent/date/reply. Keep redirects for already delivered `/replies/:id` links and approved old button URL patterns. A static approved URL cannot be replaced with an arbitrary dynamic URL parameter.
- Not present in supplied list: dedicated activity contracts for water/BP/sugar/general health/tea/walk/afternoon rest; dedicated sibling welcome/phone-change acknowledgment; expanded medicine contract beyond parent name + medicine description. Confirm live inventory and prepare any genuinely missing contracts without claiming approval.
- Medicine variable content must preserve name/dose/appearance/instructions without mangling template grammar, including Telugu/Hindi. Never use medicine templates for unrelated health checks.