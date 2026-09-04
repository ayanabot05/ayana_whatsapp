"""
templates_data.py — AYANA v2 message templates.

Core changes from v1:
  - SLOT_VARIANTS: rotational variants per category/language (3 for Nitya,
    up to 7 for Bandham/Raksha — the caller trims to the plan's limit).
  - Nicknames rotate day-to-day via get_nicknames_for_day().
  - seasonal_greeting() makes the morning line depend on the month, not
    a static "చల్లగా ఉందా".
  - No "spouse" concept anywhere — only other_parent_name / "Amma/Nanna".
  - 5 approved WhatsApp Content templates still cover all categories via
    CATEGORY_TO_TEMPLATE, unchanged from v1's opener/medicine/meal/mood/
    reengagement structure — only the copy underneath changed.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("ayana.templates")

LANGUAGES = [
    {"code": "en", "label": "English"},
    {"code": "te", "label": "తెలుగు (Telugu)"},
    {"code": "hi", "label": "हिंदी (Hindi)"},
]

# Adding a language: append it here (code + label). That's it — no other
# code change needed. en/te/hi are hand-written in SLOT_VARIANTS below
# (zero latency, zero AI cost, full editorial control over tone). Any
# other code added to LANGUAGES is served via render_slot_body_async(),
# which AI-translates + permanently caches each category the first time
# it's requested in that language — see translation_engine.py.
STATIC_LANGUAGES = frozenset(("en", "te", "hi"))


def get_language_label(code: str) -> str:
    for lang in LANGUAGES:
        if lang["code"] == code:
            return lang["label"]
    return code

RELATIONSHIPS = ["mother", "father"]

# ── Category → underlying approved template type (5 templates total) ───────
CATEGORY_TO_TEMPLATE = {
    "morning_wish": "opener",
    "medicine": "medicine", "water": "medicine", "bp_check": "medicine",
    "sugar_check": "medicine", "health_check": "medicine",
    "breakfast": "meal", "lunch": "meal", "dinner": "meal",
    "afternoon_checkin": "meal", "tea_check": "meal", "walk_check": "meal",
    "how_feeling": "mood", "goodnight": "mood", "love_note": "mood",
}

CHECKIN_CATEGORIES = {
    "morning_wish", "breakfast", "lunch", "dinner", "afternoon_checkin",
    "tea_check", "walk_check", "how_feeling", "goodnight", "love_note",
}
REMINDER_CATEGORIES = {"medicine", "water", "bp_check", "sugar_check", "health_check"}


def category_type(category: str) -> str:
    return "reminder" if category in REMINDER_CATEGORIES else "checkin"


def get_template_sid_key(category: str) -> str:
    """Which of the 5 approved templates (opener/medicine/meal/mood/reengagement) to use."""
    return CATEGORY_TO_TEMPLATE.get(category, "opener")


# ── Relationship label (short {{2}} value for the opener template) ─────────
RELATION_LABEL = {
    "mother": {"en": "Amma", "te": "అమ్మ", "hi": "माँ"},
    "father": {"en": "Nanna", "te": "నాన్న", "hi": "पापा"},
}


def parent_relation_label(parent: dict, language: str) -> str:
    rel = parent.get("relationship", "mother")
    labels = RELATION_LABEL.get(rel, RELATION_LABEL["mother"])
    return labels.get(language, labels["en"])


# ── Seasonal greeting (month-based; city kept for a future weather API) ────
_SEASON_PHRASES = {
    "winter": {"en": "a bit cold", "te": "చలిగా ఉందా", "hi": "थोड़ी ठंड है"},
    "summer": {"en": "quite warm", "te": "ఎండగా ఉందా", "hi": "गर्मी है"},
    "monsoon": {"en": "rainy", "te": "వర్షం పడుతోందా", "hi": "बारिश हो रही है"},
    "pleasant": {"en": "pleasant", "te": "ఎలా ఉంది", "hi": "मौसम अच्छा है"},
}


def seasonal_greeting(language: str = "en", month: int | None = None) -> str:
    m = month or datetime.now(timezone.utc).month
    if m in (12, 1, 2):
        key = "winter"
    elif m in (3, 4, 5):
        key = "summer"
    elif m in (6, 7, 8, 9):
        key = "monsoon"
    else:
        key = "pleasant"
    return _SEASON_PHRASES[key].get(language, _SEASON_PHRASES[key]["en"])


# ── Nickname rotation ────────────────────────────────────────────────────
def get_nicknames_for_day(parent: dict, day_index: int) -> tuple[str, str, str]:
    """
    Returns (nick1, nick2, nick3) for template variables, rotating which
    nickname is "primary" each day so the message doesn't feel static.
    Falls back to preferred_name / name if fewer than 3 nicknames are set.
    """
    fallback = parent.get("preferred_name") or parent.get("name") or "Amma"
    nicks = [n for n in (parent.get("nicknames") or []) if n] or [fallback]
    # pad to 3 by cycling
    while len(nicks) < 3:
        nicks.append(nicks[len(nicks) % len(nicks)])
    n = len(nicks)
    i = day_index % n
    return nicks[i], nicks[(i + 1) % n], nicks[(i + 2) % n]


# ── SLOT_VARIANTS — rotational message copy per category × language ────────
# Each list holds up to 7 variants; Nitya truncates to the first 3
# (trim_variants_for_plan below), Bandham/Raksha use all 7.
SLOT_VARIANTS: dict[str, dict[str, list[str]]] = {
    "morning_wish": {
        "en": [
            "Good morning {nick1} ☀ {city} morning is {season} — how did you sleep?",
            "{nick2}, had good sleep? 😊",
            "Good morning {nick1}, up already? Hope you slept well.",
            "{nick1}, morning walk done? 🚶‍♀️",
            "Hello {nick1} 🌸 thinking of you this morning.",
            "Good morning {nick2} — {city} is {season} today.",
            "Morning {nick3}, did you have your {tea_type} yet?",
        ],
        "te": [
            "శుభోదయం {nick1} ☀ {city}లో {season}? నిద్ర బాగా పట్టిందా?",
            "{nick2}, నిద్ర బాగా పట్టిందా? 😊",
            "శుభోదయం {nick1}, లేచావా? బాగా నిద్రపోయావా?",
            "{nick1}, వాకింగ్‌కి వెళ్ళావా? 🚶‍♀️",
            "హలో {nick1} 🌸 పొద్దున్నే నీ గుర్తొచ్చింది.",
            "శుభోదయం {nick2} — {city}లో {season}.",
            "{nick3}, {tea_type} తాగావా?",
        ],
        "hi": [
            "गुड मॉर्निंग {nick1} ☀ {city} में आज {season} — नींद अच्छी आई?",
            "{nick2}, नींद अच्छी आई? 😊",
            "गुड मॉर्निंग {nick1}, उठ गईं? अच्छी नींद आई?",
            "{nick1}, सुबह की सैर हो गई? 🚶‍♀️",
            "हैलो {nick1} 🌸 सुबह-सुबह आपकी याद आई।",
            "गुड मॉर्निंग {nick2} — {city} में आज {season}।",
            "{nick3}, {tea_type} पी ली?",
        ],
    },
    "breakfast": {
        "en": [
            "{nick1}, had your breakfast? 🍵 Don't skip it!",
            "Tiffin done, {nick2}?",
            "{nick1}, eat properly this morning, don't rush 😊",
            "Breakfast time {nick3} — what did you have?",
            "{nick1}, please don't skip breakfast today.",
            "Morning meal done, {nick2}? 🍵",
            "{nick1}, hope breakfast was good today.",
        ],
        "te": [
            "{nick1}, టిఫిన్ చేసావా? 🍵 మానకు!",
            "టిఫిన్ అయ్యిందా, {nick2}?",
            "{nick1}, తొందర పడకుండా తిను 😊",
            "బ్రేక్ఫాస్ట్ టైం {nick3} — ఏం తిన్నావ్?",
            "{nick1}, ఈరోజు టిఫిన్ మానకు.",
            "పొద్దున్న తిండి అయ్యిందా, {nick2}? 🍵",
            "{nick1}, టిఫిన్ బాగుందా ఈరోజు?",
        ],
        "hi": [
            "{nick1}, नाश्ता किया? 🍵 छोड़ना मत!",
            "नाश्ता हो गया, {nick2}?",
            "{nick1}, आराम से खाना, जल्दबाज़ी मत करना 😊",
            "नाश्ते का समय {nick3} — क्या खाया?",
            "{nick1}, आज नाश्ता मत छोड़ना।",
            "सुबह का खाना हो गया, {nick2}? 🍵",
            "{nick1}, आज नाश्ता अच्छा था?",
        ],
    },
    "lunch": {
        "en": [
            "{nick1}, lunch time! 🍽 Eat well and rest a little after.",
            "Bhojanam ayindha, {nick2}?",
            "{nick1}, did {other_parent} have lunch too?",
            "Lunch done, {nick3}? Don't skip it.",
            "{nick1}, eating on time today?",
            "Afternoon meal, {nick2} — all good? 🍽",
            "{nick1}, hope lunch was good.",
        ],
        "te": [
            "{nick1}, భోజనం టైం! 🍽 బాగా తిని కాసేపు రెస్ట్ తీసుకో.",
            "భోజనం అయ్యిందా, {nick2}?",
            "{nick1}, {other_parent} కూడా భోజనం చేశారా?",
            "లంచ్ అయ్యిందా, {nick3}? మానకు.",
            "{nick1}, టైంకి తింటున్నావా ఈరోజు?",
            "మధ్యాహ్న భోజనం, {nick2} — బాగుందా? 🍽",
            "{nick1}, భోజనం బాగుందా?",
        ],
        "hi": [
            "{nick1}, खाने का समय! 🍽 अच्छे से खाना, फिर थोड़ा आराम करना।",
            "खाना खाया, {nick2}?",
            "{nick1}, {other_parent} ने भी खाना खाया?",
            "लंच हो गया, {nick3}? छोड़ना मत।",
            "{nick1}, आज समय पर खाना खाया?",
            "दोपहर का खाना, {nick2} — ठीक रहा? 🍽",
            "{nick1}, खाना अच्छा था?",
        ],
    },
    "afternoon_checkin": {
        "en": [
            "{nick1}, what are you up to? 🌼 Take rest in the afternoon.",
            "{nick2}, resting a little?",
            "{nick1}, afternoon check-in — all good?",
            "{nick3}, don't overdo it this afternoon.",
            "{nick1}, how's the afternoon going?",
            "{nick2}, taking it easy today? 🌼",
            "{nick1}, quick hello from me this afternoon.",
        ],
        "te": [
            "{nick1}, ఏం చేస్తున్నావ్? 🌼 మధ్యాహ్నం కాసేపు పడుకో.",
            "{nick2}, కాసేపు రెస్ట్ తీసుకున్నావా?",
            "{nick1}, మధ్యాహ్నం చెక్-ఇన్ — బాగున్నావా?",
            "{nick3}, మధ్యాహ్నం ఎక్కువ కష్టపడకు.",
            "{nick1}, మధ్యాహ్నం ఎలా గడుస్తోంది?",
            "{nick2}, ఈరోజు రిలాక్స్‌గా ఉన్నావా? 🌼",
            "{nick1}, మధ్యాహ్నం పలకరింపు.",
        ],
        "hi": [
            "{nick1}, क्या कर रही हैं? 🌼 दोपहर में थोड़ा आराम कर लेना।",
            "{nick2}, थोड़ा आराम किया?",
            "{nick1}, दोपहर का हाल — सब ठीक?",
            "{nick3}, दोपहर में ज़्यादा मेहनत मत करना।",
            "{nick1}, दोपहर कैसी जा रही है?",
            "{nick2}, आज आराम से हैं? 🌼",
            "{nick1}, बस दोपहर का हैलो।",
        ],
    },
    "tea_check": {
        "en": [
            "{nick1}, had your {tea_type}? ☕",
            "Tea time, {nick2}? ☕",
            "{nick1}, did {other_parent} have {tea_type} too?",
            "Evening tea done, {nick3}?",
            "{nick2}, how was your {tea_type}?",
            "{nick1}, {tea_type} break time?",
            "Hi {nick1}, tea break? ☕",
        ],
        "te": [
            "{nick1}, {tea_type} తాగారా? ☕",
            "టీ టైం, {nick2}? ☕",
            "{nick1}, {other_parent} కూడా టీ తాగారా?",
            "సాయంత్రం టీ అయ్యిందా, {nick3}?",
            "{nick2}, టీ ఎలా ఉంది?",
            "{nick1}, టీ బ్రేక్ టైం అయ్యిందా?",
            "హాయ్ {nick1}, టీ బ్రేకా? ☕",
        ],
        "hi": [
            "{nick1}, {tea_type} पी ली? ☕",
            "चाय का समय, {nick2}? ☕",
            "{nick1}, {other_parent} ने भी चाय पी?",
            "शाम की चाय हो गई, {nick3}?",
            "{nick2}, चाय कैसी थी?",
            "{nick1}, चाय ब्रेक का समय हो गया?",
            "हाय {nick1}, चाय ब्रेक? ☕",
        ],
    },
    "walk_check": {
        "en": [
            "{nick1}, walk done today? 🚶‍♀️",
            "{nick2}, went for a walk?",
            "{nick1}, evening walk time — going out?",
            "{nick3}, a short walk today?",
            "{nick1}, feet up or a little walk today?",
            "{nick2}, walk done? 🚶",
            "{nick1}, hope you got some fresh air today.",
        ],
        "te": [
            "{nick1}, ఈరోజు వాకింగ్ అయ్యిందా? 🚶‍♀️",
            "{nick2}, వాకింగ్‌కి వెళ్ళావా?",
            "{nick1}, సాయంత్రం వాక్ టైం — వెళ్తున్నావా?",
            "{nick3}, ఈరోజు కాసేపు వాక్?",
            "{nick1}, ఈరోజు కాళ్ళు రెస్ట్ ఇచ్చావా, వాక్ చేశావా?",
            "{nick2}, వాకింగ్ అయ్యిందా? 🚶",
            "{nick1}, ఈరోజు కాసేపు గాలి పీల్చుకున్నావా?",
        ],
        "hi": [
            "{nick1}, आज सैर हो गई? 🚶‍♀️",
            "{nick2}, टहलने गईं?",
            "{nick1}, शाम की सैर का समय — जा रही हैं?",
            "{nick3}, आज थोड़ी टहलना?",
            "{nick1}, आज आराम किया या टहली?",
            "{nick2}, सैर हो गई? 🚶",
            "{nick1}, आज थोड़ी ताज़ी हवा मिली?",
        ],
    },
    "how_feeling": {
        "en": [
            "{nick1}, how are you feeling right now? 💛",
            "Ela unnav, {nick2}? Thinking of you 💛",
            "{nick1}, just checking in on you.",
            "{nick3}, all good today?",
            "{nick1}, how's your day been so far?",
            "{nick2}, feeling okay? 💛",
            "{nick1}, quick check — how are you?",
        ],
        "te": [
            "{nick1}, ఇప్పుడు ఎలా ఉన్నావ్? 💛",
            "ఏం చేస్తున్నావ్, {nick2}? నీ గురించే ఆలోచిస్తున్నా 💛",
            "{nick1}, నీ గురించి కులాసానా అని అడగాలనిపించింది.",
            "{nick3}, ఈరోజు బాగున్నావా?",
            "{nick1}, ఈరోజు ఎలా గడిచింది ఇప్పటివరకూ?",
            "{nick2}, బాగున్నావా? 💛",
            "{nick1}, ఒక్క మాట — ఎలా ఉన్నావ్?",
        ],
        "hi": [
            "{nick1}, अभी कैसा महसूस हो रहा है? 💛",
            "क्या कर रही हैं, {nick2}? आपकी याद आ रही थी 💛",
            "{nick1}, बस आपका हाल पूछ रहा हूँ।",
            "{nick3}, आज सब ठीक?",
            "{nick1}, आज का दिन कैसा जा रहा है?",
            "{nick2}, ठीक महसूस हो रहा है? 💛",
            "{nick1}, बस एक सवाल — कैसी हैं आप?",
        ],
    },
    "goodnight": {
        "en": [
            "Goodnight {nick1} 🌟 How was your day? Sleep well, love you.",
            "Sleep tight, {nick2} ✨ Miss you.",
            "{nick1}, how did today go? Rest well.",
            "{nick3}, time to wind down for the night.",
            "Goodnight {nick1} — talk tomorrow!",
            "{nick2}, hope you had a good day. Sleep well 🌙",
            "{nick1}, sending you goodnight wishes 🌟",
        ],
        "te": [
            "శుభరాత్రి {nick1} 🌟 ఈరోజు ఎలా జరిగింది? హాయిగా నిద్రపో, లవ్ యూ.",
            "బజ్జోవే {nick2} ✨ నిన్ను మిస్ అవుతున్నా.",
            "{nick1}, ఈరోజు ఎలా గడిచింది? రెస్ట్ తీసుకో.",
            "{nick3}, ఇక నిద్రపోయే టైం.",
            "శుభరాత్రి {nick1} — రేపు మాట్లాడదాం!",
            "{nick2}, ఈరోజు బాగా గడిచిందా ఆశిస్తున్నా. హాయిగా నిద్రపో 🌙",
            "{nick1}, శుభరాత్రి చెప్పాలనిపించింది 🌟",
        ],
        "hi": [
            "शुभ रात्रि {nick1} 🌟 आज का दिन कैसा रहा? चैन से सोना, लव यू।",
            "सो जाओ, {nick2} ✨ याद आती है।",
            "{nick1}, आज कैसा रहा दिन? आराम करना।",
            "{nick3}, अब सोने का समय हो गया।",
            "शुभ रात्रि {nick1} — कल बात करते हैं!",
            "{nick2}, उम्मीद है आज का दिन अच्छा रहा। चैन से सोना 🌙",
            "{nick1}, बस शुभ रात्रि कहना था 🌟",
        ],
    },
    "love_note": {
        "en": [
            "Just wanted to say I love you {nick1} ❤ Distance means nothing.",
            "Miss you a lot, {nick2} ❤",
            "{nick1}, you're always on my mind.",
            "{nick3}, sending you love today ❤",
            "{nick1}, thinking of you and smiling.",
            "{nick2}, just a little love note for you today ❤",
            "{nick1}, grateful for you always.",
        ],
        "te": [
            "నిన్ను చాలా ప్రేమిస్తున్నా {nick1} ❤ దూరం పెద్ద విషయం కాదు.",
            "చాలా మిస్ అవుతున్నా, {nick2} ❤",
            "{nick1}, ఎప్పుడూ నీ గురించే ఆలోచన.",
            "{nick3}, ఈరోజు నీకు ప్రేమ పంపిస్తున్నా ❤",
            "{nick1}, నీ గురించి ఆలోచిస్తూ నవ్వుతున్నా.",
            "{nick2}, ఈరోజు ఒక చిన్న ప్రేమ సందేశం ❤",
            "{nick1}, నువ్వు ఉన్నందుకు కృతజ్ఞతలు.",
        ],
        "hi": [
            "बस इतना कहना था, बहुत प्यार करता/करती हूँ {nick1} ❤ दूरी कोई मायने नहीं रखती।",
            "बहुत याद आती है, {nick2} ❤",
            "{nick1}, हमेशा आपका ख्याल रहता है।",
            "{nick3}, आज आपके लिए प्यार भेज रहा/रही हूँ ❤",
            "{nick1}, आपके बारे में सोचकर मुस्कुरा रहा/रही हूँ।",
            "{nick2}, आज बस एक छोटा प्यार भरा संदेश ❤",
            "{nick1}, आपके लिए हमेशा आभारी हूँ।",
        ],
    },
    "medicine": {
        "en": [
            "{nick1}, medicine time 💊 Please take your {medicine} — don't forget!",
            "Mandulu vesukunnava, {nick2}? 💊",
            "{nick1}, time for {medicine}.",
            "{nick3}, please don't skip your {medicine} today.",
            "{nick1}, medicine reminder — {medicine} 💊",
            "{nick2}, take care of your health — {medicine} time.",
            "{nick1}, gentle reminder for {medicine} 💊",
        ],
        "te": [
            "{nick1}, మందుల టైం 💊 మీ {medicine} వేసుకోండి — మర్చిపోకండి!",
            "మందులు వేసుకున్నావా, {nick2}? 💊",
            "{nick1}, {medicine} టైం అయ్యింది.",
            "{nick3}, ఈరోజు {medicine} మానకు.",
            "{nick1}, మందుల రిమైండర్ — {medicine} 💊",
            "{nick2}, ఆరోగ్యం జాగ్రత్త — {medicine} టైం.",
            "{nick1}, {medicine} కోసం చిన్న రిమైండర్ 💊",
        ],
        "hi": [
            "{nick1}, दवाई का समय 💊 अपनी {medicine} ले लेना — भूलना नहीं!",
            "दवाई ली, {nick2}? 💊",
            "{nick1}, {medicine} का समय हो गया।",
            "{nick3}, आज {medicine} मत छोड़ना।",
            "{nick1}, दवाई रिमाइंडर — {medicine} 💊",
            "{nick2}, सेहत का ख्याल रखना — {medicine} का समय।",
            "{nick1}, {medicine} के लिए छोटा रिमाइंडर 💊",
        ],
    },
    "water": {
        "en": ["{nick1}, drink some water 💧 Even a small sip helps!",
               "{nick2}, had water recently?",
               "{nick1}, stay hydrated today 💧"],
        "te": ["{nick1}, కొంచెం నీళ్ళు తాగు 💧 చిన్న సిప్ అయినా సరే!",
               "{nick2}, ఇటీవల నీళ్ళు తాగావా?",
               "{nick1}, ఈరోజు హైడ్రేటెడ్‌గా ఉండు 💧"],
        "hi": ["{nick1}, थोड़ा पानी पी लो 💧 थोड़ा सा ही सही!",
               "{nick2}, हाल ही में पानी पिया?",
               "{nick1}, आज हाइड्रेटेड रहना 💧"],
    },
    "health_check": {
        "en": ["{nick1}, how's your health today? 🩺 Any pain or discomfort?",
               "{nick2}, feeling okay physically?",
               "{nick1}, quick health check-in 🩺"],
        "te": ["{nick1}, ఈరోజు ఆరోగ్యం ఎలా ఉంది? 🩺 ఏమైనా నొప్పి ఉందా?",
               "{nick2}, శారీరకంగా బాగున్నావా?",
               "{nick1}, చిన్న హెల్త్ చెక్-ఇన్ 🩺"],
        "hi": ["{nick1}, आज तबीयत कैसी है? 🩺 कोई दर्द या तकलीफ़?",
               "{nick2}, शारीरिक रूप से ठीक हैं?",
               "{nick1}, छोटा हेल्थ चेक-इन 🩺"],
    },
    "bp_check": {
        "en": ["{nick1}, time to check your BP 🩸 Note it down for the doctor.",
               "{nick2}, BP checked today?",
               "{nick1}, BP check reminder 🩸"],
        "te": ["{nick1}, బీపీ చెక్ చేసుకునే టైం 🩸 డాక్టర్ కోసం రాసిపెట్టు.",
               "{nick2}, ఈరోజు బీపీ చెక్ చేసుకున్నావా?",
               "{nick1}, బీపీ చెక్ రిమైండర్ 🩸"],
        "hi": ["{nick1}, बीपी चेक करने का समय 🩸 डॉक्टर के लिए लिख लेना।",
               "{nick2}, आज बीपी चेक किया?",
               "{nick1}, बीपी चेक रिमाइंडर 🩸"],
    },
    "sugar_check": {
        "en": ["{nick1}, please check your sugar levels 🩸 Before eating, okay?",
               "{nick2}, sugar checked today?",
               "{nick1}, sugar check reminder 🩸"],
        "te": ["{nick1}, తినే ముందు షుగర్ చెక్ చేసుకో 🩸 సరేనా?",
               "{nick2}, ఈరోజు షుగర్ చెక్ చేసుకున్నావా?",
               "{nick1}, షుగర్ చెక్ రిమైండర్ 🩸"],
        "hi": ["{nick1}, खाने से पहले शुगर चेक कर लेना 🩸 ठीक है?",
               "{nick2}, आज शुगर चेक किया?",
               "{nick1}, शुगर चेक रिमाइंडर 🩸"],
    },
}


def trim_variants_for_plan(variants: list[str], variants_per_slot: int) -> list[str]:
    return variants[:max(1, variants_per_slot)]


def render_slot_body(
    category: str,
    language: str,
    parent: dict,
    day_index: int = 0,
    medicine_name: str = "your medicine",
    variants_per_slot: int = 7,
) -> str:
    """
    Picks a rotating variant for (category, language), fills in nicknames,
    seasonal greeting, city, other_parent, story, medicine, tea_type.
    `variants_per_slot` should come from the parent's plan (Nitya=3, else 7).
    """
    bucket = SLOT_VARIANTS.get(category) or SLOT_VARIANTS.get("how_feeling", {})
    variants = bucket.get(language) or bucket.get("en", ["{nick1}, thinking of you 💛"])
    variants = trim_variants_for_plan(variants, variants_per_slot)
    template = variants[day_index % len(variants)]

    nick1, nick2, nick3 = get_nicknames_for_day(parent, day_index)
    habits = parent.get("habits") or {}
    stories = parent.get("stories") or []
    story = stories[day_index % len(stories)] if stories else ""

    return template.format(
        nick1=nick1, nick2=nick2, nick3=nick3,
        city=parent.get("city") or "your city",
        season=seasonal_greeting(language),
        other_parent=parent.get("other_parent_name") or ("Amma" if parent.get("relationship") == "father" else "Nanna"),
        story=story,
        medicine=medicine_name,
        tea_type=habits.get("tea_type", "tea") if language == "en" else ("కాఫీ" if habits.get("tea_type") == "coffee" else "టీ") if language == "te" else ("कॉफ़ी" if habits.get("tea_type") == "coffee" else "चाय"),
    )


async def get_variants_async(category: str, language: str) -> list[str]:
    """
    Fast path (en/te/hi): returns the hand-written SLOT_VARIANTS list —
    no DB read, no network call, zero added latency or token cost.

    Adaptive path (any other language): delegates entirely to
    translation_engine.get_variants(), which owns both the cache
    (template_variants_cache — the Postgres table schema.sql creates)
    and the Sarvam translation call. That function returns
    None on any failure (disabled, unsupported language, API error) —
    we fall back to the English copy in that case rather than crashing,
    matching what translation_engine.py's docstring promises callers.
    This is what makes new-language support additive (edit LANGUAGES,
    nothing else) rather than a code change.

    MIGRATION NOTE: dropped the `db` parameter — translation_engine.py
    now imports the Postgres pool directly, same pattern used
    throughout this migration.
    """
    bucket = SLOT_VARIANTS.get(category) or SLOT_VARIANTS.get("how_feeling", {})
    if language in bucket:
        return bucket[language]

    english = bucket.get("en") or ["{nick1}, thinking of you 💛"]
    if language not in STATIC_LANGUAGES:
        from translation_engine import get_variants as get_dynamic_variants
        variants = await get_dynamic_variants(category, language)
        if variants:
            return variants
        return english

    return english


async def render_slot_body_async(
    category: str,
    language: str,
    parent: dict,
    day_index: int = 0,
    medicine_name: str = "your medicine",
    variants_per_slot: int = 7,
) -> str:
    """
    Async counterpart to render_slot_body — identical placeholder-filling
    logic, but sources variants via get_variants_async so languages
    outside en/te/hi resolve through the AI-translation cache instead of
    silently falling back to English mid-sentence.

    MIGRATION NOTE: dropped the `db` parameter — matches whatsapp.py's
    call sites, which no longer pass one.
    """
    variants = await get_variants_async(category, language)
    variants = trim_variants_for_plan(variants, variants_per_slot)
    template = variants[day_index % len(variants)]

    nick1, nick2, nick3 = get_nicknames_for_day(parent, day_index)
    habits = parent.get("habits") or {}
    stories = parent.get("stories") or []
    story = stories[day_index % len(stories)] if stories else ""

    tea_type_raw = habits.get("tea_type", "tea")
    if language == "te":
        tea_display = "కాఫీ" if tea_type_raw == "coffee" else "టీ"
    elif language == "hi":
        tea_display = "कॉफ़ी" if tea_type_raw == "coffee" else "चाय"
    else:
        tea_display = tea_type_raw

    return template.format(
        nick1=nick1, nick2=nick2, nick3=nick3,
        city=parent.get("city") or "your city",
        season=seasonal_greeting(language),
        other_parent=parent.get("other_parent_name") or ("Amma" if parent.get("relationship") == "father" else "Nanna"),
        story=story,
        medicine=medicine_name,
        tea_type=tea_display,
    )


# ── Tap-only quick-reply buttons (language-aware, no typing 1/2/3) ─────────
BUTTONS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "morning_wish": {
        "en": [("Good 😊", "feeling:good"), ("Okay 🙂", "feeling:okay"), ("Not well 😟", "feeling:not_well")],
        "te": [("😊 బాగున్నా", "feeling:good"), ("😐 ఫర్వాలేదు", "feeling:okay"), ("😟 బాలేదు", "feeling:not_well")],
        "hi": [("😊 ठीक हूँ", "feeling:good"), ("😐 ठीक-ठाक", "feeling:okay"), ("😟 ठीक नहीं", "feeling:not_well")],
    },
    "how_feeling": {
        "en": [("Good 😊", "feeling:good"), ("Okay 🙂", "feeling:okay"), ("Not well 😟", "feeling:not_well")],
        "te": [("😊 బాగున్నా", "feeling:good"), ("😐 ఫర్వాలేదు", "feeling:okay"), ("😟 బాలేదు", "feeling:not_well")],
        "hi": [("😊 ठीक हूँ", "feeling:good"), ("😐 ठीक-ठाक", "feeling:okay"), ("😟 ठीक नहीं", "feeling:not_well")],
    },
    "goodnight": {
        "en": [("Good day 😊", "feeling:good"), ("Average 🙂", "feeling:okay"), ("Tired 😟", "feeling:not_well")],
        "te": [("😊 బాగుంది", "feeling:good"), ("😐 పర్వాలేదు", "feeling:okay"), ("😔 అలసిపోయా", "feeling:not_well")],
        "hi": [("😊 अच्छा दिन", "feeling:good"), ("😐 ठीक दिन", "feeling:okay"), ("😔 थक गई", "feeling:not_well")],
    },
    "love_note": {
        "en": [("Love you too ❤", "feeling:good"), ("Thanks 🙏", "feeling:okay"), ("Missing you", "feeling:okay")],
        "te": [("❤ లవ్ యూ టూ", "feeling:good"), ("🙏 థాంక్స్", "feeling:okay"), ("😔 మిస్ యూ", "feeling:okay")],
        "hi": [("❤ लव यू टू", "feeling:good"), ("🙏 शुक्रिया", "feeling:okay"), ("😔 याद आती है", "feeling:okay")],
    },
    "medicine": {
        "en": [("Done ✅", "done:medicine"), ("Not yet", "pending:medicine"), ("Skipped", "skip:medicine")],
        "te": [("✅ అయ్యింది", "done:medicine"), ("⏰ తర్వాత", "pending:medicine"), ("❌ మర్చిపోయా", "skip:medicine")],
        "hi": [("✅ हो गया", "done:medicine"), ("⏰ बाद में", "pending:medicine"), ("❌ भूल गई", "skip:medicine")],
    },
    "water": {
        "en": [("Done 💧", "done:water"), ("Will now", "pending:water"), ("Forgot", "skip:water")],
        "te": [("💧 అయ్యింది", "done:water"), ("⏰ ఇప్పుడు", "pending:water"), ("❌ మర్చిపోయా", "skip:water")],
        "hi": [("💧 हो गया", "done:water"), ("⏰ अभी", "pending:water"), ("❌ भूल गई", "skip:water")],
    },
    "bp_check": {
        "en": [("Checked ✅", "done:bp"), ("Not yet", "pending:bp"), ("No machine", "skip:bp")],
        "te": [("✅ చెక్ చేసా", "done:bp"), ("⏰ తర్వాత", "pending:bp"), ("❌ మెషిన్ లేదు", "skip:bp")],
        "hi": [("✅ चेक किया", "done:bp"), ("⏰ बाद में", "pending:bp"), ("❌ मशीन नहीं", "skip:bp")],
    },
    "sugar_check": {
        "en": [("Checked ✅", "done:sugar"), ("Not yet", "pending:sugar"), ("No machine", "skip:sugar")],
        "te": [("✅ చెక్ చేసా", "done:sugar"), ("⏰ తర్వాత", "pending:sugar"), ("❌ మెషిన్ లేదు", "skip:sugar")],
        "hi": [("✅ चेक किया", "done:sugar"), ("⏰ बाद में", "pending:sugar"), ("❌ मशीन नहीं", "skip:sugar")],
    },
    "health_check": {
        "en": [("All good 🩺", "feeling:good"), ("Some pain", "feeling:not_well"), ("Bad day 😟", "emergency:health")],
        "te": [("🩺 బాగుంది", "feeling:good"), ("😟 నొప్పి", "feeling:not_well"), ("🚨 బాలేదు", "emergency:health")],
        "hi": [("🩺 ठीक है", "feeling:good"), ("😟 दर्द है", "feeling:not_well"), ("🚨 खराब", "emergency:health")],
    },
    "breakfast": {
        "en": [("Had it 🍵", "done:breakfast"), ("Having now", "pending:breakfast"), ("Not hungry", "skip:breakfast")],
        "te": [("🍵 అయ్యింది", "done:breakfast"), ("⏰ తర్వాత", "pending:breakfast"), ("😔 ఆకలి లేదు", "skip:breakfast")],
        "hi": [("🍵 खा लिया", "done:breakfast"), ("⏰ बाद में", "pending:breakfast"), ("😔 भूख नहीं", "skip:breakfast")],
    },
    "lunch": {
        "en": [("Had it 🍽", "done:lunch"), ("Not yet", "pending:lunch"), ("Not hungry", "skip:lunch")],
        "te": [("🍽 అయ్యింది", "done:lunch"), ("⏰ తర్వాత", "pending:lunch"), ("😔 ఆకలి లేదు", "skip:lunch")],
        "hi": [("🍽 खा लिया", "done:lunch"), ("⏰ बाद में", "pending:lunch"), ("😔 भूख नहीं", "skip:lunch")],
    },
    "dinner": {
        "en": [("Done 🌙", "done:dinner"), ("Not yet", "pending:dinner"), ("Skipping", "skip:dinner")],
        "te": [("🌙 అయ్యింది", "done:dinner"), ("⏰ తర్వాత", "pending:dinner"), ("😔 వద్దు", "skip:dinner")],
        "hi": [("🌙 खा लिया", "done:dinner"), ("⏰ बाद में", "pending:dinner"), ("😔 नहीं", "skip:dinner")],
    },
    "afternoon_checkin": {
        "en": [("Resting 🛌", "done:rest"), ("Busy", "pending:rest"), ("Not well 😟", "feeling:not_well")],
        "te": [("🛌 పడుకున్నా", "done:rest"), ("⏰ బిజీ", "pending:rest"), ("😟 బాలేదు", "feeling:not_well")],
        "hi": [("🛌 आराम", "done:rest"), ("⏰ व्यस्त", "pending:rest"), ("😟 ठीक नहीं", "feeling:not_well")],
    },
    "tea_check": {
        "en": [("Done ☕", "done:tea"), ("Now", "pending:tea"), ("Skipped", "skip:tea")],
        "te": [("☕ అయ్యింది", "done:tea"), ("⏰ ఇప్పుడే", "pending:tea"), ("❌ లేదు", "skip:tea")],
        "hi": [("☕ हो गया", "done:tea"), ("⏰ अभी", "pending:tea"), ("❌ नहीं", "skip:tea")],
    },
    "walk_check": {
        "en": [("Done 🚶‍♀️", "done:walk"), ("Later", "pending:walk"), ("Not today", "skip:walk")],
        "te": [("🚶‍♀️ అయ్యింది", "done:walk"), ("⏰ తర్వాత", "pending:walk"), ("❌ ఈరోజు లేదు", "skip:walk")],
        "hi": [("🚶‍♀️ हो गया", "done:walk"), ("⏰ बाद में", "pending:walk"), ("❌ आज नहीं", "skip:walk")],
    },
}


def render_slot_buttons(category: str, language: str = "en") -> list[tuple[str, str]]:
    slot = BUTTONS.get(category, BUTTONS["how_feeling"])
    return slot.get(language, slot["en"])[:3]


DEFAULT_EMERGENCY_KEYWORDS = [
    "help", "emergency", "pain", "fell", "fall", "hospital", "chest pain", "breathless", "dizzy",
    "not well", "sick", "so sick",
    "సహాయం", "అత్యవసరం", "నొప్పి", "పడిపోయాను", "పడిపోయా", "ఒంట్లో బాలేదు", "బాలేదు",
    "తల తిరుగుతోంది", "గుండె నొప్పి",
    "मदद", "आपातकाल", "दर्द", "गिर गया", "तबीयत ठीक नहीं", "तबीयत खराब", "सांस नहीं", "सीने में दर्द",
]


def public_categories():
    return [{"key": k, "type": category_type(k)} for k in SLOT_VARIANTS.keys()]