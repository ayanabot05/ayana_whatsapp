"""
templates_data.py — AYANA v2 message templates.
Conversational, warm, and fully button-matched to Meta-approved strings.

IMPORTANT:
- Template names are unchanged.
- Language codes are unchanged: en, te, hi.
- Button responses are matched to the question/category.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger("ayana.templates")

LANGUAGES = [
    {"code": "en", "label": "English"},
    {"code": "te", "label": "తెలుగు (Telugu)"},
    {"code": "hi", "label": "हिंदी (Hindi)"},
]

STATIC_LANGUAGES = frozenset(("en", "te", "hi"))

RELATIONSHIPS = ["mother", "father"]


# ── Category → underlying approved template type (5 templates total) ───────
CATEGORY_TO_TEMPLATE = {
    "morning_wish": "opener",

    "medicine": "medicine",
    "water": "medicine",
    "bp_check": "medicine",
    "sugar_check": "medicine",
    "health_check": "medicine",

    "breakfast": "meal",
    "lunch": "meal",
    "dinner": "meal",
    "afternoon_checkin": "meal",
    "tea_check": "meal",
    "walk_check": "meal",

    "how_feeling": "mood",
    "goodnight": "mood",
    "love_note": "mood",
}


CHECKIN_CATEGORIES = {
    "morning_wish",
    "breakfast",
    "lunch",
    "dinner",
    "afternoon_checkin",
    "goodnight",
    "love_note",
}

REMINDER_CATEGORIES = {
    "medicine",
    "water",
    "bp_check",
    "sugar_check",
    "health_check",
}

ACTIVITY_CATEGORIES = {
    "walk_check",
    "tea_check",
    "how_feeling",
}


def category_type(category: str) -> str:
    if category in REMINDER_CATEGORIES:
        return "reminder"
    if category in ACTIVITY_CATEGORIES:
        return "activity"
    return "checkin"


def get_template_sid_key(category: str) -> str:
    return CATEGORY_TO_TEMPLATE.get(category, "opener")


# ── Relationship label ──────────────────────────────────────────────────────
RELATION_LABEL = {
    "mother": {
        "en": "Amma",
        "te": "అమ్మ",
        "hi": "माँ",
    },
    "father": {
        "en": "Nanna",
        "te": "నాన్న",
        "hi": "पापा",
    },
}


def parent_relation_label(parent: dict, language: str) -> str:
    rel = parent.get("relationship", "mother")
    labels = RELATION_LABEL.get(rel, RELATION_LABEL["mother"])
    return labels.get(language, labels["en"])


# ── Seasonal greeting ────────────────────────────────────────────────────────
_SEASON_PHRASES = {
    "winter": {
        "en": "a bit cold",
        "te": "చలిగా ఉందా",
        "hi": "थोड़ी ठंड है",
    },
    "summer": {
        "en": "quite warm",
        "te": "ఎండగా ఉందా",
        "hi": "गर्मी है",
    },
    "monsoon": {
        "en": "rainy",
        "te": "వర్షం పడుతోందా",
        "hi": "बारिश हो रही है",
    },
    "pleasant": {
        "en": "pleasant",
        "te": "ఎలా ఉంది",
        "hi": "मौसम अच्छा है",
    },
}


def seasonal_greeting(
    language: str = "en",
    month: int | None = None,
) -> str:
    m = month or datetime.now(timezone.utc).month

    if m in (12, 1, 2):
        key = "winter"
    elif m in (3, 4, 5):
        key = "summer"
    elif m in (6, 7, 8, 9):
        key = "monsoon"
    else:
        key = "pleasant"

    return _SEASON_PHRASES[key].get(
        language,
        _SEASON_PHRASES[key]["en"],
    )


# ── Nickname rotation ───────────────────────────────────────────────────────
def get_nicknames_for_day(
    parent: dict,
    day_index: int,
) -> tuple[str, str, str]:

    fallback = (
        parent.get("preferred_name")
        or parent.get("name")
        or "Amma"
    )

    nicks = [
        n
        for n in (parent.get("nicknames") or [])
        if n
    ] or [fallback]

    while len(nicks) < 3:
        nicks.append(
            nicks[len(nicks) % len(nicks)]
        )

    n = len(nicks)
    i = day_index % n

    return (
        nicks[i],
        nicks[(i + 1) % n],
        nicks[(i + 2) % n],
    )


# ────────────────────────────────────────────────────────────────────────────
# SLOT_VARIANTS
# ────────────────────────────────────────────────────────────────────────────

SLOT_VARIANTS: dict[str, dict[str, list[str]]] = {

    # ────────────────────────────────────────────────────────────────────────
    # MORNING
    # Question → How did you sleep?
    # ────────────────────────────────────────────────────────────────────────
    "morning_wish": {
        "en": [
            "Good morning {nick1} ☀️ How did you sleep? Stay hydrated.",
            "{nick2}, you're up! How was your sleep? 😊",
            "Good morning {nick1}! Any nice dreams? 🌸",
            "{nick3}, morning breeze feels nice? Take it easy.",
            "Wake up {nick2}! Let's start the day with a smile. 😄",
        ],
        "te": [
            "శుభోదయం {nick1} ☀️ నిద్ర బాగా పట్టిందా? లేవగానే కాస్త నీళ్లు తాగు.",
            "{nick2}, లేచావా? రాత్రి నిద్ర ఎలా ఉంది? 😊",
            "శుభోదయం {nick1}! ఏమైనా కలలు కన్నావా? 🌸",
            "{nick3}, పొద్దున్నే హాయిగా ఉందా? రెస్ట్ తీసుకో.",
            "లే {nick2}! నీ నోటి దగ్గర నవ్వు ఉందా? 😄",
        ],
        "hi": [
            "सुप्रभात {nick1} ☀️ नींद अच्छी आई? उठते ही पानी पी लेना।",
            "{nick2}, जाग गए? रात कैसी रही? 😊",
            "सुप्रभात {nick1}! कोई अच्छा सपना देखा? 🌸",
            "{nick3}, सुबह की हवा अच्छी है? थोड़ा आराम करो।",
            "जाओ {nick2}! आज की शुरुआत हँसी से करो। 😄",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # BREAKFAST
    # ────────────────────────────────────────────────────────────────────────
    "breakfast": {
        "en": [
            "{nick1}, had breakfast? 🍵",
            "Breakfast time, {nick2}. Have you eaten?",
            "{nick1}, don't skip breakfast today 😊",
            "Tiffin time, {nick3} — eaten yet?",
            "{nick1}, have you had something to eat?",
        ],
        "te": [
            "{nick1}, టిఫిన్ అయ్యిందా? 🍵",
            "టిఫిన్ టైం, {nick2}. తిన్నావా?",
            "{nick1}, ఈరోజు టిఫిన్ మానకు 😊",
            "టిఫిన్ టైం {nick3} — తిన్నావా?",
            "{nick1}, ఏమైనా తిన్నావా?",
        ],
        "hi": [
            "{nick1}, नाश्ता हो गया? 🍵",
            "नाश्ते का समय है, {nick2}. कुछ खाया?",
            "{nick1}, आज नाश्ता मत छोड़ना 😊",
            "नाश्ते का समय {nick3} — खाया?",
            "{nick1}, कुछ खाया है?",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # LUNCH
    # ────────────────────────────────────────────────────────────────────────
    "lunch": {
        "en": [
            "{nick1}, lunch time! 🍽️ Have you eaten?",
            "Bhojanam time, {nick2}. Lunch done?",
            "{nick1}, have you had lunch yet?",
            "Lunch time {nick3} — don't skip it.",
            "{nick1}, eating on time today?",
        ],
        "te": [
            "{nick1}, భోజనం టైం! 🍽️ తిన్నావా?",
            "భోజనం టైం, {nick2}. భోజనం అయ్యిందా?",
            "{nick1}, భోజనం చేశావా?",
            "లంచ్ టైం {nick3} — మానకు.",
            "{nick1}, ఈరోజు టైంకి తింటున్నావా?",
        ],
        "hi": [
            "{nick1}, खाने का समय! 🍽️ खाना खाया?",
            "खाने का समय है, {nick2}. खाना हो गया?",
            "{nick1}, खाना खा लिया?",
            "लंच का समय {nick3} — खाना मत छोड़ना।",
            "{nick1}, आज समय पर खाना खाया?",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # DINNER
    # ────────────────────────────────────────────────────────────────────────
    "dinner": {
        "en": [
            "{nick1}, dinner time! 🌙 Have you eaten?",
            "Dinner time, {nick2}. Eat well and rest.",
            "{nick1}, have you had dinner yet?",
            "Dinner done, {nick3}? Don't skip.",
            "{nick1}, eating dinner on time today?",
        ],
        "te": [
            "{nick1}, రాత్రి భోజనం టైం! 🌙 తిన్నావా?",
            "డిన్నర్ టైం, {nick2}. బాగా తిని రెస్ట్ తీసుకో.",
            "{nick1}, రాత్రి భోజనం చేశావా?",
            "డిన్నర్ అయ్యిందా, {nick3}? మానకు.",
            "{nick1}, రాత్రి టైంకి తింటున్నావా?",
        ],
        "hi": [
            "{nick1}, रात के खाने का समय! 🌙 खाना खाया?",
            "डिनर का समय है, {nick2}. अच्छे से खाना और आराम करना।",
            "{nick1}, रात का खाना खा लिया?",
            "डिनर हो गया, {nick3}? छोड़ना मत।",
            "{nick1}, आज समय पर रात का खाना खाया?",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # AFTERNOON CHECK-IN
    # ────────────────────────────────────────────────────────────────────────
    "afternoon_checkin": {
        "en": [
            "{nick1}, what are you up to? 🌼 Take some rest this afternoon.",
            "{nick2}, what are you doing right now?",
            "{nick1}, afternoon check-in — how's your day going?",
            "{nick3}, taking a little break this afternoon?",
            "{nick1}, how's your afternoon going?",
        ],
        "te": [
            "{nick1}, ఏం చేస్తున్నావ్? 🌼 మధ్యాహ్నం కాసేపు రెస్ట్ తీసుకో.",
            "{nick2}, ఇప్పుడు ఏం చేస్తున్నావ్?",
            "{nick1}, మధ్యాహ్నం చెక్-ఇన్ — రోజు ఎలా గడుస్తోంది?",
            "{nick3}, మధ్యాహ్నం కాసేపు రెస్ట్ తీసుకుంటున్నావా?",
            "{nick1}, మధ్యాహ్నం ఎలా గడుస్తోంది?",
        ],
        "hi": [
            "{nick1}, क्या कर रही हैं? 🌼 दोपहर में थोड़ा आराम कर लेना।",
            "{nick2}, अभी क्या कर रही हैं?",
            "{nick1}, दोपहर का हाल — दिन कैसा जा रहा है?",
            "{nick3}, दोपहर में थोड़ा आराम कर रही हैं?",
            "{nick1}, दोपहर कैसी जा रही है?",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # TEA
    # ────────────────────────────────────────────────────────────────────────
    "tea_check": {
        "en": [
            "{nick1}, had your {tea_type}? ☕",
            "Tea time, {nick2}? Have you had your {tea_type}?",
            "{nick1}, ready for your {tea_type} break?",
            "Evening {tea_type} done, {nick3}?",
            "Hi {nick1}, having your {tea_type}? ☕",
        ],
        "te": [
            "{nick1}, {tea_type} తాగారా? ☕",
            "టీ టైం, {nick2}? {tea_type} తాగారా?",
            "{nick1}, {tea_type} తాగడానికి రెడీనా?",
            "సాయంత్రం {tea_type} అయ్యిందా, {nick3}?",
            "హాయ్ {nick1}, {tea_type} తాగుతున్నావా? ☕",
        ],
        "hi": [
            "{nick1}, {tea_type} पी ली? ☕",
            "चाय का समय, {nick2}? {tea_type} पी ली?",
            "{nick1}, {tea_type} के लिए तैयार?",
            "शाम की {tea_type} हो गई, {nick3}?",
            "हाय {nick1}, {tea_type} पी रहे हैं? ☕",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # WALK
    # ────────────────────────────────────────────────────────────────────────
    "walk_check": {
        "en": [
            "{nick1}, walk done today? 🚶‍♀️",
            "{nick2}, did you go for your walk?",
            "{nick1}, evening walk time — going out?",
            "{nick3}, planning a short walk today?",
            "{nick2}, got your steps in today? 🚶",
        ],
        "te": [
            "{nick1}, ఈరోజు వాకింగ్ అయ్యిందా? 🚶‍♀️",
            "{nick2}, వాకింగ్‌కి వెళ్ళావా?",
            "{nick1}, సాయంత్రం వాక్ టైం — వెళ్తున్నావా?",
            "{nick3}, ఈరోజు కాసేపు వాక్‌కి వెళ్తావా?",
            "{nick2}, ఈరోజు వాకింగ్ చేశావా? 🚶",
        ],
        "hi": [
            "{nick1}, आज सैर हो गई? 🚶‍♀️",
            "{nick2}, टहलने गए?",
            "{nick1}, शाम की सैर का समय — जा रहे हैं?",
            "{nick3}, आज थोड़ी सैर करने का मन है?",
            "{nick2}, आज टहलना हुआ? 🚶",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # HOW FEELING
    # ────────────────────────────────────────────────────────────────────────
    "how_feeling": {
        "en": [
            "{nick1}, how are you feeling right now? 💛",
            "How are you doing, {nick2}? Thinking of you 💛",
            "{nick1}, just checking in on you.",
            "{nick3}, how are you feeling today?",
            "{nick2}, feeling okay today? 💛",
        ],
        "te": [
            "{nick1}, ఇప్పుడు ఎలా ఉన్నావ్? 💛",
            "ఎలా ఉన్నావ్, {nick2}? నీ గురించే ఆలోచిస్తున్నా 💛",
            "{nick1}, నీ గురించి అడగాలనిపించింది.",
            "{nick3}, ఈరోజు ఎలా అనిపిస్తోంది?",
            "{nick2}, బాగానే అనిపిస్తుందా? 💛",
        ],
        "hi": [
            "{nick1}, अभी कैसा महसूस हो रहा है? 💛",
            "कैसी हैं, {nick2}? आपकी याद आ रही थी 💛",
            "{nick1}, बस आपका हाल पूछ रहा हूँ।",
            "{nick3}, आज कैसा महसूस हो रहा है?",
            "{nick2}, आज ठीक महसूस हो रहा है? 💛",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # GOODNIGHT
    # ────────────────────────────────────────────────────────────────────────
    "goodnight": {
        "en": [
            "Goodnight {nick1} 🌟 How was your day?",
            "Sleep tight, {nick2} ✨ How did today go?",
            "{nick1}, how was your day? Rest well.",
            "{nick3}, time to wind down. How was today?",
            "Goodnight {nick1} — how did today treat you?",
        ],
        "te": [
            "శుభరాత్రి {nick1} 🌟 ఈరోజు ఎలా జరిగింది?",
            "హాయిగా నిద్రపో, {nick2} ✨ ఈరోజు ఎలా గడిచింది?",
            "{nick1}, ఈరోజు ఎలా గడిచింది? రెస్ట్ తీసుకో.",
            "{nick3}, ఇక నిద్రపోయే టైం. ఈరోజు ఎలా ఉంది?",
            "శుభరాత్రి {nick1} — ఈరోజు ఎలా అనిపించింది?",
        ],
        "hi": [
            "शुभ रात्रि {nick1} 🌟 आज का दिन कैसा रहा?",
            "सो जाइए, {nick2} ✨ आज का दिन कैसा रहा?",
            "{nick1}, आज दिन कैसा रहा? आराम करना।",
            "{nick3}, अब आराम करने का समय है। आज का दिन कैसा रहा?",
            "शुभ रात्रि {nick1} — आज का दिन कैसा रहा?",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # LOVE NOTE
    # ────────────────────────────────────────────────────────────────────────
    "love_note": {
        "en": [
            "Just wanted to say I love you {nick1} ❤️",
            "Miss you a lot, {nick2} ❤️",
            "{nick1}, you're always on my mind.",
            "{nick3}, sending you lots of love today ❤️",
            "{nick2}, just a little love note for you today ❤️",
        ],
        "te": [
            "నిన్ను చాలా ప్రేమిస్తున్నా {nick1} ❤️",
            "చాలా మిస్ అవుతున్నా, {nick2} ❤️",
            "{nick1}, ఎప్పుడూ నీ గురించే ఆలోచిస్తున్నా.",
            "{nick3}, ఈరోజు నీకు చాలా ప్రేమ పంపిస్తున్నా ❤️",
            "{nick2}, ఈరోజు నీ కోసం ఒక చిన్న ప్రేమ సందేశం ❤️",
        ],
        "hi": [
            "बस इतना कहना था, बहुत प्यार करता/करती हूँ {nick1} ❤️",
            "बहुत याद आती है, {nick2} ❤️",
            "{nick1}, हमेशा आपका ख्याल रहता है।",
            "{nick3}, आज आपके लिए ढेर सारा प्यार ❤️",
            "{nick2}, आज बस आपके लिए एक छोटा सा प्यार भरा संदेश ❤️",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # MEDICINE
    # ────────────────────────────────────────────────────────────────────────
    "medicine": {
        "en": [
            "{nick1}, medicine time 💊 Please take your {medicine}.",
            "Did you take your {medicine}, {nick2}?",
            "{nick1}, it's time for {medicine}.",
            "{nick3}, please don't forget your {medicine} today.",
            "{nick2}, take care — {medicine} time.",
        ],
        "te": [
            "{nick1}, మందు టైమ్ 💊 {medicine} వేసుకున్నావా?",
            "{nick2}, {medicine} వేసుకున్నావా?",
            "{nick1}, {medicine} టైం అయ్యింది.",
            "{nick3}, ఈరోజు {medicine} మర్చిపోకు.",
            "{nick2}, ఆరోగ్యం జాగ్రత్త — {medicine} టైం.",
        ],
        "hi": [
            "{nick1}, दवा का समय है 💊 {medicine} ले ली?",
            "{nick2}, {medicine} ले ली?",
            "{nick1}, {medicine} का समय हो गया।",
            "{nick3}, आज {medicine} लेना मत भूलना।",
            "{nick2}, सेहत का ख्याल — {medicine} का समय।",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # WATER
    # ────────────────────────────────────────────────────────────────────────
    "water": {
        "en": [
            "{nick1}, drink some water 💧 Even a small sip helps!",
            "{nick2}, have you had water recently?",
            "{nick1}, time for some water 💧",
        ],
        "te": [
            "{nick1}, కొంచెం నీళ్ళు తాగు 💧 చిన్న సిప్ అయినా సరే!",
            "{nick2}, ఇటీవల నీళ్ళు తాగావా?",
            "{nick1}, కాస్త నీళ్ళు తాగే టైం 💧",
        ],
        "hi": [
            "{nick1}, थोड़ा पानी पी लो 💧 थोड़ा सा ही सही!",
            "{nick2}, हाल ही में पानी पिया?",
            "{nick1}, थोड़ा पानी पीने का समय 💧",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # HEALTH CHECK
    # ────────────────────────────────────────────────────────────────────────
    "health_check": {
        "en": [
            "{nick1}, how's your health today? 🩺 Any pain?",
            "{nick2}, are you feeling okay physically?",
            "{nick1}, quick health check-in 🩺 How are you feeling?",
        ],
        "te": [
            "{nick1}, ఈరోజు ఆరోగ్యం ఎలా ఉంది? 🩺 ఏమైనా నొప్పి ఉందా?",
            "{nick2}, శారీరకంగా బాగున్నావా?",
            "{nick1}, చిన్న హెల్త్ చెక్-ఇన్ 🩺 ఎలా అనిపిస్తోంది?",
        ],
        "hi": [
            "{nick1}, आज तबीयत कैसी है? 🩺 कोई दर्द या तकलीफ़?",
            "{nick2}, शारीरिक रूप से ठीक हैं?",
            "{nick1}, छोटा हेल्थ चेक-इन 🩺 कैसा महसूस हो रहा है?",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # BP CHECK
    # ────────────────────────────────────────────────────────────────────────
    "bp_check": {
        "en": [
            "{nick1}, time to check your BP 🩸",
            "{nick2}, have you checked your BP today?",
            "{nick1}, BP check time 🩸 Remember to note the reading.",
        ],
        "te": [
            "{nick1}, బీపీ చెక్ చేసుకునే టైం 🩸",
            "{nick2}, ఈరోజు బీపీ చెక్ చేసుకున్నావా?",
            "{nick1}, బీపీ చెక్ టైం 🩸 రీడింగ్ రాసిపెట్టు.",
        ],
        "hi": [
            "{nick1}, बीपी चेक करने का समय 🩸",
            "{nick2}, आज बीपी चेक किया?",
            "{nick1}, बीपी चेक का समय 🩸 रीडिंग लिख लेना।",
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # SUGAR CHECK
    # ────────────────────────────────────────────────────────────────────────
    "sugar_check": {
        "en": [
            "{nick1}, time to check your sugar 🩸",
            "{nick2}, have you checked your sugar today?",
            "{nick1}, sugar check time 🩸",
        ],
        "te": [
            "{nick1}, షుగర్ చెక్ చేసుకునే టైం 🩸",
            "{nick2}, ఈరోజు షుగర్ చెక్ చేసుకున్నావా?",
            "{nick1}, షుగర్ చెక్ టైం 🩸",
        ],
        "hi": [
            "{nick1}, शुगर चेक करने का समय 🩸",
            "{nick2}, आज शुगर चेक किया?",
            "{nick1}, शुगर चेक का समय 🩸",
        ],
    },
}


# ────────────────────────────────────────────────────────────────────────────
# BUTTONS
#
# IMPORTANT PRODUCT PRINCIPLE:
#
# Buttons must answer the question above them.
#
# Morning:
#   "How did you sleep?"
#   → Sleep-specific answers
#
# Goodnight:
#   "How was your day?"
#   → Day-specific answers
#
# How feeling:
#   "How are you feeling?"
#   → Feeling-specific answers
#
# Meals:
#   "Have you eaten?"
#   → Meal-specific answers
#
# Medicine:
#   "Did you take your medicine?"
#   → Medicine-specific answers
# ────────────────────────────────────────────────────────────────────────────

BUTTONS: dict[str, dict[str, list[tuple[str, str]]]] = {

    # ────────────────────────────────────────────────────────────────────────
    # MORNING WISH
    # Question: How did you sleep?
    # ────────────────────────────────────────────────────────────────────────
    "morning_wish": {
        "en": [
            ("Slept really well 😴", "sleep:good"),
            ("Not bad 🙂", "sleep:okay"),
            ("Didn't sleep well 😔", "sleep:poor"),
        ],
        "te": [
            ("బాగా నిద్రపోయాను 😴", "sleep:good"),
            ("పర్లేదు 🙂", "sleep:okay"),
            ("సరిగ్గా నిద్రపోలేదు 😔", "sleep:poor"),
        ],
        "hi": [
            ("बहुत अच्छी नींद आई 😴", "sleep:good"),
            ("ठीक-ठाक थी 🙂", "sleep:okay"),
            ("अच्छी नींद नहीं आई 😔", "sleep:poor"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # HOW FEELING
    # Question: How are you feeling?
    # ────────────────────────────────────────────────────────────────────────
    "how_feeling": {
        "en": [
            ("Feeling good 😊", "feeling:good"),
            ("A little tired 😌", "feeling:tired"),
            ("Not feeling well 😟", "feeling:not_well"),
        ],
        "te": [
            ("బాగున్నాను 😊", "feeling:good"),
            ("కాస్త అలసటగా ఉంది 😌", "feeling:tired"),
            ("బాగోలేదు 😟", "feeling:not_well"),
        ],
        "hi": [
            ("अच्छा लग रहा है 😊", "feeling:good"),
            ("थोड़ी थकान है 😌", "feeling:tired"),
            ("ठीक नहीं लग रहा 😟", "feeling:not_well"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # GOODNIGHT
    # Question: How was your day?
    # ────────────────────────────────────────────────────────────────────────
    "goodnight": {
        "en": [
            ("It was a good day 😊", "day:good"),
            ("It was okay 🙂", "day:okay"),
            ("It was tiring 😴", "day:tiring"),
        ],
        "te": [
            ("ఈరోజు బాగుంది 😊", "day:good"),
            ("పర్లేదు 🙂", "day:okay"),
            ("చాలా అలసటగా ఉంది 😴", "day:tiring"),
        ],
        "hi": [
            ("दिन अच्छा था 😊", "day:good"),
            ("ठीक-ठाक था 🙂", "day:okay"),
            ("दिन थकाने वाला था 😴", "day:tiring"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # LOVE NOTE
    # Emotional response — NOT a health survey.
    # ────────────────────────────────────────────────────────────────────────
    "love_note": {
        "en": [
            ("Love you too ❤️", "love:reply"),
            ("Miss you too 🥰", "love:miss_you"),
            ("Call me when free 📞", "love:call"),
        ],
        "te": [
            ("నేను కూడా ప్రేమిస్తున్నా ❤️", "love:reply"),
            ("నేను కూడా మిస్ అవుతున్నా 🥰", "love:miss_you"),
            ("టైం దొరికినప్పుడు కాల్ చెయ్ 📞", "love:call"),
        ],
        "hi": [
            ("मैं भी तुमसे प्यार करता/करती हूँ ❤️", "love:reply"),
            ("मुझे भी तुम्हारी याद आती है 🥰", "love:miss_you"),
            ("समय मिले तो कॉल करना 📞", "love:call"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # HEALTH CHECK
    # Question: How's your health? Any pain?
    # ────────────────────────────────────────────────────────────────────────
    "health_check": {
        "en": [
            ("Feeling fine 🩺", "health:fine"),
            ("I have some pain 😟", "health:pain"),
            ("I need help 🚨", "emergency:health"),
        ],
        "te": [
            ("బాగానే ఉన్నాను 🩺", "health:fine"),
            ("కొంచెం నొప్పిగా ఉంది 😟", "health:pain"),
            ("నాకు సహాయం కావాలి 🚨", "emergency:health"),
        ],
        "hi": [
            ("ठीक हूँ 🩺", "health:fine"),
            ("थोड़ा दर्द है 😟", "health:pain"),
            ("मुझे मदद चाहिए 🚨", "emergency:health"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # MEDICINE
    # Question: Did you take your medicine?
    # ────────────────────────────────────────────────────────────────────────
    "medicine": {
        "en": [
            ("Taken ✅", "done:medicine"),
            ("I'll take it now ⏰", "pending:medicine"),
            ("Skipped today ❌", "skip:medicine"),
        ],
        "te": [
            ("వేసుకున్నా ✅", "done:medicine"),
            ("ఇప్పుడు వేసుకుంటా ⏰", "pending:medicine"),
            ("ఈరోజు వేసుకోలేదు ❌", "skip:medicine"),
        ],
        "hi": [
            ("ले ली ✅", "done:medicine"),
            ("अभी ले लूँगा/लूँगी ⏰", "pending:medicine"),
            ("आज नहीं ली ❌", "skip:medicine"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # WATER
    # Question: Did you drink water?
    # ────────────────────────────────────────────────────────────────────────
    "water": {
        "en": [
            ("Just drank some 💧", "done:water"),
            ("I'll drink now 💧", "pending:water"),
            ("I forgot 😅", "skip:water"),
        ],
        "te": [
            ("ఇప్పుడే తాగాను 💧", "done:water"),
            ("ఇప్పుడు తాగుతా 💧", "pending:water"),
            ("మర్చిపోయా 😅", "skip:water"),
        ],
        "hi": [
            ("अभी पानी पिया 💧", "done:water"),
            ("अभी पीता/पीती हूँ 💧", "pending:water"),
            ("भूल गया/गई 😅", "skip:water"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # BP CHECK
    # Question: Did you check your BP?
    # ────────────────────────────────────────────────────────────────────────
    "bp_check": {
        "en": [
            ("Checked it ✅", "done:bp"),
            ("I'll check now ⏰", "pending:bp"),
            ("No machine here", "skip:bp"),
        ],
        "te": [
            ("చెక్ చేసుకున్నా ✅", "done:bp"),
            ("ఇప్పుడు చెక్ చేసుకుంటా ⏰", "pending:bp"),
            ("ఇక్కడ మెషిన్ లేదు", "skip:bp"),
        ],
        "hi": [
            ("चेक कर लिया ✅", "done:bp"),
            ("अभी चेक करूँगा/करूँगी ⏰", "pending:bp"),
            ("यहाँ मशीन नहीं है", "skip:bp"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # SUGAR CHECK
    # Question: Did you check your sugar?
    # ────────────────────────────────────────────────────────────────────────
    "sugar_check": {
        "en": [
            ("Checked it ✅", "done:sugar"),
            ("I'll check now ⏰", "pending:sugar"),
            ("No machine here", "skip:sugar"),
        ],
        "te": [
            ("చెక్ చేసుకున్నా ✅", "done:sugar"),
            ("ఇప్పుడు చెక్ చేసుకుంటా ⏰", "pending:sugar"),
            ("ఇక్కడ మెషిన్ లేదు", "skip:sugar"),
        ],
        "hi": [
            ("चेक कर लिया ✅", "done:sugar"),
            ("अभी चेक करूँगा/करूँगी ⏰", "pending:sugar"),
            ("यहाँ मशीन नहीं है", "skip:sugar"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # BREAKFAST
    # Question: Did you eat breakfast?
    # ────────────────────────────────────────────────────────────────────────
    "breakfast": {
        "en": [
            ("Had breakfast 🍽️", "done:breakfast"),
            ("Eating now ⏰", "pending:breakfast"),
            ("Skipped it ❌", "skip:breakfast"),
        ],
        "te": [
            ("టిఫిన్ తిన్నాను 🍽️", "done:breakfast"),
            ("ఇప్పుడు తింటున్నా ⏰", "pending:breakfast"),
            ("టిఫిన్ మానేశాను ❌", "skip:breakfast"),
        ],
        "hi": [
            ("नाश्ता कर लिया 🍽️", "done:breakfast"),
            ("अभी कर रहा/रही हूँ ⏰", "pending:breakfast"),
            ("नाश्ता नहीं किया ❌", "skip:breakfast"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # LUNCH
    # Question: Did you eat lunch?
    # ────────────────────────────────────────────────────────────────────────
    "lunch": {
        "en": [
            ("Had lunch 🍽️", "done:lunch"),
            ("Not yet ⏰", "pending:lunch"),
            ("Skipped lunch ❌", "skip:lunch"),
        ],
        "te": [
            ("భోజనం చేశాను 🍽️", "done:lunch"),
            ("ఇంకా చేయలేదు ⏰", "pending:lunch"),
            ("భోజనం మానేశాను ❌", "skip:lunch"),
        ],
        "hi": [
            ("खाना खा लिया 🍽️", "done:lunch"),
            ("अभी नहीं ⏰", "pending:lunch"),
            ("खाना छोड़ दिया ❌", "skip:lunch"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # DINNER
    # Question: Did you eat dinner?
    # ────────────────────────────────────────────────────────────────────────
    "dinner": {
        "en": [
            ("Had dinner 🌙", "done:dinner"),
            ("Eating now ⏰", "pending:dinner"),
            ("Skipping tonight ❌", "skip:dinner"),
        ],
        "te": [
            ("తిన్నాను 🌙", "done:dinner"),
            ("ఇప్పుడు తింటున్నా ⏰", "pending:dinner"),
            ("ఈరోజు మానేశాను ❌", "skip:dinner"),
        ],
        "hi": [
            ("खा लिया 🌙", "done:dinner"),
            ("अभी खा रहा/रही हूँ ⏰", "pending:dinner"),
            ("आज नहीं खाऊँगा/खाऊँगी ❌", "skip:dinner"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # AFTERNOON CHECK-IN
    # Question: What are you doing?
    # ────────────────────────────────────────────────────────────────────────
    "afternoon_checkin": {
        "en": [
            ("Just resting 🛌", "activity:resting"),
            ("Doing some work 🏠", "activity:busy"),
            ("Out for something 🚶", "activity:out"),
        ],
        "te": [
            ("కాసేపు రెస్ట్ 🛌", "activity:resting"),
            ("పని చేస్తున్నా 🏠", "activity:busy"),
            ("బయటికి వెళ్లాను 🚶", "activity:out"),
        ],
        "hi": [
            ("बस आराम 🛌", "activity:resting"),
            ("कुछ काम कर रहा/रही हूँ 🏠", "activity:busy"),
            ("बाहर गया/गई हूँ 🚶", "activity:out"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # TEA CHECK
    # Question: Did you have tea/coffee?
    # ────────────────────────────────────────────────────────────────────────
    "tea_check": {
        "en": [
            ("Had it ☕", "done:tea"),
            ("Having it now ☕", "pending:tea"),
            ("Skipped it", "skip:tea"),
        ],
        "te": [
            ("తాగాను ☕", "done:tea"),
            ("ఇప్పుడు తాగుతున్నా ☕", "pending:tea"),
            ("మానేశాను", "skip:tea"),
        ],
        "hi": [
            ("पी ली ☕", "done:tea"),
            ("अभी पी रहा/रही हूँ ☕", "pending:tea"),
            ("नहीं पी", "skip:tea"),
        ],
    },


    # ────────────────────────────────────────────────────────────────────────
    # WALK CHECK
    # Question: Did you go for a walk?
    # ────────────────────────────────────────────────────────────────────────
    "walk_check": {
        "en": [
            ("Yes, done 🚶", "done:walk"),
            ("Going later ⏰", "pending:walk"),
            ("Not today", "skip:walk"),
        ],
        "te": [
            ("అవును, చేశాను 🚶", "done:walk"),
            ("తర్వాత వెళ్తాను ⏰", "pending:walk"),
            ("ఈరోజు లేదు", "skip:walk"),
        ],
        "hi": [
            ("हाँ, हो गई 🚶", "done:walk"),
            ("बाद में जाऊँगा/जाऊँगी ⏰", "pending:walk"),
            ("आज नहीं", "skip:walk"),
        ],
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def render_slot_buttons(
    category: str,
    language: str = "en",
) -> list[tuple[str, str]]:
    """
    Return the three buttons for a category/language.

    Falls back safely to how_feeling/en if a category or language
    is unexpectedly missing.
    """

    slot = BUTTONS.get(
        category,
        BUTTONS["how_feeling"],
    )

    return slot.get(
        language,
        slot["en"],
    )[:3]


def trim_variants_for_plan(
    variants: list[str],
    variants_per_slot: int,
) -> list[str]:
    return variants[:max(1, variants_per_slot)]


def _render_slot(
    category: str,
    language: str,
    parent: dict,
    day_index: int = 0,
    medicine_name: str = "your medicine",
    variants_per_slot: int = 7,
) -> str:

    bucket = SLOT_VARIANTS.get(
        category
    ) or SLOT_VARIANTS.get(
        "how_feeling",
        {},
    )

    variants = (
        bucket.get(language)
        or bucket.get(
            "en",
            ["{nick1}, thinking of you 💛"],
        )
    )

    variants = trim_variants_for_plan(
        variants,
        variants_per_slot,
    )

    template = variants[
        day_index % len(variants)
    ]

    nick1, nick2, nick3 = get_nicknames_for_day(
        parent,
        day_index,
    )

    habits = parent.get("habits") or {}

    stories = parent.get("stories") or []

    story = (
        stories[day_index % len(stories)]
        if stories
        else ""
    )

    tea_type_raw = habits.get(
        "tea_type",
        "tea",
    )

    if language == "te":
        tea_display = (
            "కాఫీ"
            if tea_type_raw == "coffee"
            else "టీ"
        )

    elif language == "hi":
        tea_display = (
            "कॉफ़ी"
            if tea_type_raw == "coffee"
            else "चाय"
        )

    else:
        tea_display = tea_type_raw

    return template.format(
        nick1=nick1,
        nick2=nick2,
        nick3=nick3,
        city=parent.get("city") or "your city",
        season=seasonal_greeting(language),
        other_parent=(
            parent.get("other_parent_name")
            or (
                "Amma"
                if parent.get("relationship") == "father"
                else "Nanna"
            )
        ),
        story=story,
        medicine=medicine_name,
        tea_type=tea_display,
    )


def render_slot_body(
    category: str,
    language: str,
    parent: dict,
    day_index: int = 0,
    medicine_name: str = "your medicine",
    variants_per_slot: int = 7,
) -> str:

    return _render_slot(
        category=category,
        language=language,
        parent=parent,
        day_index=day_index,
        medicine_name=medicine_name,
        variants_per_slot=variants_per_slot,
    )


async def render_slot_body_async(
    category: str,
    language: str,
    parent: dict,
    day_index: int = 0,
    medicine_name: str = "your medicine",
    variants_per_slot: int = 7,
) -> str:

    return _render_slot(
        category=category,
        language=language,
        parent=parent,
        day_index=day_index,
        medicine_name=medicine_name,
        variants_per_slot=variants_per_slot,
    )


# ── Emergency keywords ───────────────────────────────────────────────────────

DEFAULT_EMERGENCY_KEYWORDS = [
    # English
    "help",
    "emergency",
    "pain",
    "fell",
    "fall",
    "hospital",
    "chest pain",
    "breathless",
    "dizzy",
    "not well",
    "sick",
    "so sick",

    # Telugu
    "సహాయం",
    "అత్యవసరం",
    "నొప్పి",
    "పడిపోయాను",
    "పడిపోయా",
    "ఒంట్లో బాలేదు",
    "బాలేదు",
    "తల తిరుగుతోంది",
    "గుండె నొప్పి",

    # Hindi
    "मदद",
    "आपातकाल",
    "दर्द",
    "गिर गया",
    "तबीयत ठीक नहीं",
    "तबीयत खराब",
    "सांस नहीं",
    "सीने में दर्द",
]


def public_categories():
    return [
        {
            "key": k,
            "type": category_type(k),
        }
        for k in SLOT_VARIANTS.keys()
    ]

