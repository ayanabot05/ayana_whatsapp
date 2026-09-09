"""
templates_data.py — AYANA v2 message templates.
Conversational, warm, and fully button‑matched to Meta‑approved strings.
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
    "medicine": "medicine", "water": "medicine", "bp_check": "medicine",
    "sugar_check": "medicine", "health_check": "medicine",
    "breakfast": "meal", "lunch": "meal", "dinner": "meal",
    "afternoon_checkin": "meal", "tea_check": "meal", "walk_check": "meal",
    "how_feeling": "mood", "goodnight": "mood", "love_note": "mood",
}

CHECKIN_CATEGORIES = {
    "morning_wish", "breakfast", "lunch", "dinner", "afternoon_checkin",
    "goodnight", "love_note",
}

REMINDER_CATEGORIES = {"medicine", "water", "bp_check", "sugar_check", "health_check"}
ACTIVITY_CATEGORIES = {"walk_check", "tea_check", "how_feeling"}


def category_type(category: str) -> str:
    if category in REMINDER_CATEGORIES:
        return "reminder"
    if category in ACTIVITY_CATEGORIES:
        return "activity"
    return "checkin"


def get_template_sid_key(category: str) -> str:
    return CATEGORY_TO_TEMPLATE.get(category, "opener")


# ── Relationship label ─────────────────────────────────────────────────────────
RELATION_LABEL = {
    "mother": {"en": "Amma", "te": "అమ్మ", "hi": "माँ"},
    "father": {"en": "Nanna", "te": "నాన్న", "hi": "पापा"},
}

def parent_relation_label(parent: dict, language: str) -> str:
    rel = parent.get("relationship", "mother")
    labels = RELATION_LABEL.get(rel, RELATION_LABEL["mother"])
    return labels.get(language, labels["en"])


# ── Seasonal greeting ────────────────────────────────────────────────────────
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


# ── Nickname rotation ──────────────────────────────────────────────────────
def get_nicknames_for_day(parent: dict, day_index: int) -> tuple[str, str, str]:
    fallback = parent.get("preferred_name") or parent.get("name") or "Amma"
    nicks = [n for n in (parent.get("nicknames") or []) if n] or [fallback]
    while len(nicks) < 3:
        nicks.append(nicks[len(nicks) % len(nicks)])
    n = len(nicks)
    i = day_index % n
    return nicks[i], nicks[(i + 1) % n], nicks[(i + 2) % n]


# ── SLOT_VARIANTS — conversational, culturally warm copy ──────────────────
SLOT_VARIANTS: dict[str, dict[str, list[str]]] = {
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
    "breakfast": {
        "en": ["{nick1}, had breakfast? What did you eat? 🍵",
               "Tiffin done, {nick2}?",
               "{nick1}, eat well, don't rush 😊",
               "Breakfast time {nick3} — have you eaten yet?",
               "{nick1}, don't skip breakfast today."],
        "te": ["{nick1}, టిఫిన్ అయ్యిందా? ఏం తిన్నావ్? 🍵",
               "టిఫిన్ అయ్యిందా, {nick2}?",
               "{nick1}, తొందర పడకుండా తిను 😊",
               "బ్రేక్ఫాస్ట్ టైం {nick3} — తిన్నావా?",
               "{nick1}, ఈరోజు టిఫిన్ మానకు."],
        "hi": ["{nick1}, नाश्ता हो गया? क्या खाया? 🍵",
               "नाश्ता हो गया, {nick2}?",
               "{nick1}, आराम से खाना, जल्दबाज़ी मत करना 😊",
               "नाश्ते का समय {nick3} — कुछ खाया?",
               "{nick1}, आज नाश्ता मत छोड़ना।"],
    },
    "lunch": {
        "en": ["{nick1}, lunch time! 🍽 What did you cook today?",
               "Bhojanam ayindha, {nick2}?",
               "{nick1}, did {other_parent} have lunch too?",
               "Lunch done, {nick3}? Don't skip.",
               "{nick1}, eating on time today?"],
        "te": ["{nick1}, భోజనం చేసావా? ఏం వండారు? 🍽",
               "భోజనం అయ్యిందా, {nick2}?",
               "{nick1}, {other_parent} కూడా భోజనం చేశారా?",
               "లంచ్ అయ్యిందా, {nick3}? మానకు.",
               "{nick1}, టైంకి తింటున్నావా ఈరోజు?"],
        "hi": ["{nick1}, खाना खाया? क्या बना है? 🍽",
               "खाना खाया, {nick2}?",
               "{nick1}, {other_parent} ने भी खाना खाया?",
               "लंच हो गया, {nick3}? छोड़ना मत।",
               "{nick1}, आज समय पर खाना खाया?"],
    },
    "dinner": {
        "en": ["{nick1}, dinner time! 🌙 Eat well and rest.",
               "Ratri bhojanam ayindha, {nick2}?",
               "{nick1}, did {other_parent} have dinner too?",
               "Dinner done, {nick3}? Don't skip.",
               "{nick1}, eating dinner on time today?"],
        "te": ["{nick1}, రాత్రి భోజనం చేసావా? ఏం తిన్నావ్? 🌙",
               "రాత్రి భోజనం అయ్యిందా, {nick2}?",
               "{nick1}, {other_parent} కూడా రాత్రి భోజనం చేశారా?",
               "డిన్నర్ అయ్యిందా, {nick3}? మానకు.",
               "{nick1}, రాత్రి టైంకి తింటున్నావా?"],
        "hi": ["{nick1}, रात का खाना खाया? क्या खाया? 🌙",
               "रात का खाना खाया, {nick2}?",
               "{nick1}, {other_parent} ने भी रात का खाना खाया?",
               "डिनर हो गया, {nick3}? छोड़ना मत।",
               "{nick1}, आज समय पर रात का खाना खाया?"],
    },
    "afternoon_checkin": {
        "en": ["{nick1}, what are you up to? 🌼 Take rest in the afternoon.",
               "{nick2}, resting a little?",
               "{nick1}, afternoon check-in — all good?",
               "{nick3}, don't overdo it this afternoon.",
               "{nick1}, how's the afternoon going?"],
        "te": ["{nick1}, ఏం చేస్తున్నావ్? 🌼 మధ్యాహ్నం కాసేపు పడుకో.",
               "{nick2}, కాసేపు రెస్ట్ తీసుకున్నావా?",
               "{nick1}, మధ్యాహ్నం చెక్-ఇన్ — బాగున్నావా?",
               "{nick3}, మధ్యాహ్నం ఎక్కువ కష్టపడకు.",
               "{nick1}, మధ్యాహ్నం ఎలా గడుస్తోంది?"],
        "hi": ["{nick1}, क्या कर रही हैं? 🌼 दोपहर में थोड़ा आराम कर लेना।",
               "{nick2}, थोड़ा आराम किया?",
               "{nick1}, दोपहर का हाल — सब ठीक?",
               "{nick3}, दोपहर में ज़्यादा मेहनत मत करना।",
               "{nick1}, दोपहर कैसी जा रही है?"],
    },
    "tea_check": {
        "en": ["{nick1}, had your {tea_type}? ☕",
               "Tea time, {nick2}?",
               "{nick1}, did {other_parent} have {tea_type} too?",
               "Evening tea done, {nick3}?",
               "Hi {nick1}, tea break? ☕"],
        "te": ["{nick1}, {tea_type} తాగారా? ☕",
               "టీ టైం, {nick2}?",
               "{nick1}, {other_parent} కూడా టీ తాగారా?",
               "సాయంత్రం టీ అయ్యిందా, {nick3}?",
               "హాయ్ {nick1}, టీ బ్రేకా? ☕"],
        "hi": ["{nick1}, {tea_type} पी ली? ☕",
               "चाय का समय, {nick2}?",
               "{nick1}, {other_parent} ने भी चाय पी?",
               "शाम की चाय हो गई, {nick3}?",
               "हाय {nick1}, चाय ब्रेक? ☕"],
    },
    "walk_check": {
        "en": ["{nick1}, walk done today? 🚶‍♀️",
               "{nick2}, went for a walk?",
               "{nick1}, evening walk time — going out?",
               "{nick3}, a short walk today?",
               "{nick2}, walk done? 🚶"],
        "te": ["{nick1}, ఈరోజు వాకింగ్ అయ్యిందా? 🚶‍♀️",
               "{nick2}, వాకింగ్‌కి వెళ్ళావా?",
               "{nick1}, సాయంత్రం వాక్ టైం — వెళ్తున్నావా?",
               "{nick3}, ఈరోజు కాసేపు వాక్?",
               "{nick2}, వాకింగ్ అయ్యిందా? 🚶"],
        "hi": ["{nick1}, आज सैर हो गई? 🚶‍♀️",
               "{nick2}, टहलने गईं?",
               "{nick1}, शाम की सैर का समय — जा रही हैं?",
               "{nick3}, आज थोड़ी टहलना?",
               "{nick2}, सैर हो गई? 🚶"],
    },
    "how_feeling": {
        "en": ["{nick1}, how are you feeling right now? 💛",
               "Ela unnav, {nick2}? Thinking of you 💛",
               "{nick1}, just checking in on you.",
               "{nick3}, all good today?",
               "{nick2}, feeling okay? 💛"],
        "te": ["{nick1}, ఇప్పుడు ఎలా ఉన్నావ్? 💛",
               "ఏం చేస్తున్నావ్, {nick2}? నీ గురించే ఆలోచిస్తున్నా 💛",
               "{nick1}, నీ గురించి కులాసానా అని అడగాలనిపించింది.",
               "{nick3}, ఈరోజు బాగున్నావా?",
               "{nick2}, బాగున్నావా? 💛"],
        "hi": ["{nick1}, अभी कैसा महसूस हो रहा है? 💛",
               "क्या कर रही हैं, {nick2}? आपकी याद आ रही थी 💛",
               "{nick1}, बस आपका हाल पूछ रहा हूँ।",
               "{nick3}, आज सब ठीक?",
               "{nick2}, ठीक महसूस हो रहा है? 💛"],
    },
    "goodnight": {
        "en": ["Goodnight {nick1} 🌟 How was your day? Sleep well, love you.",
               "Sleep tight, {nick2} ✨ Miss you.",
               "{nick1}, how did today go? Rest well.",
               "{nick3}, time to wind down.",
               "Goodnight {nick1} — talk tomorrow!"],
        "te": ["శుభరాత్రి {nick1} 🌟 ఈరోజు ఎలా జరిగింది? హాయిగా నిద్రపో, లవ్ యూ.",
               "బజ్జోవే {nick2} ✨ నిన్ను మిస్ అవుతున్నా.",
               "{nick1}, ఈరోజు ఎలా గడిచింది? రెస్ట్ తీసుకో.",
               "{nick3}, ఇక నిద్రపోయే టైం.",
               "శుభరాత్రి {nick1} — రేపు మాట్లాడదాం!"],
        "hi": ["शुभ रात्रि {nick1} 🌟 आज का दिन कैसा रहा? चैन से सोना, लव यू।",
               "सो जाओ, {nick2} ✨ याद आती है।",
               "{nick1}, आज कैसा रहा दिन? आराम करना।",
               "{nick3}, अब सोने का समय हो गया।",
               "शुभ रात्रि {nick1} — कल बात करते हैं!"],
    },
    "love_note": {
        "en": ["Just wanted to say I love you {nick1} ❤ Distance means nothing.",
               "Miss you a lot, {nick2} ❤",
               "{nick1}, you're always on my mind.",
               "{nick3}, sending you love today ❤",
               "{nick2}, just a little love note for you today ❤"],
        "te": ["నిన్ను చాలా ప్రేమిస్తున్నా {nick1} ❤ దూరం పెద్ద విషయం కాదు.",
               "చాలా మిస్ అవుతున్నా, {nick2} ❤",
               "{nick1}, ఎప్పుడూ నీ గురించే ఆలోచన.",
               "{nick3}, ఈరోజు నీకు ప్రేమ పంపిస్తున్నా ❤",
               "{nick2}, ఈరోజు ఒక చిన్న ప్రేమ సందేశం ❤"],
        "hi": ["बस इतना कहना था, बहुत प्यार करता/करती हूँ {nick1} ❤ दूरी कोई मायने नहीं रखती।",
               "बहुत याद आती है, {nick2} ❤",
               "{nick1}, हमेशा आपका ख्याल रहता है।",
               "{nick3}, आज आपके लिए प्यार भेज रहा/रही हूँ ❤",
               "{nick2}, आज बस एक छोटा प्यार भरा संदेश ❤"],
    },
    "medicine": {
        "en": ["{nick1}, medicine time 💊 Please take your {medicine} — don't forget!",
               "Mandulu vesukunnava, {nick2}?",
               "{nick1}, time for {medicine}.",
               "{nick3}, please don't skip your {medicine} today.",
               "{nick2}, take care — {medicine} time."],
        "te": ["{nick1}, మందు టైమ్ 💊 {medicine} వేసుకున్నావా? మర్చిపోకు ప్లీజ్.",
               "మందులు వేసుకున్నావా, {nick2}?",
               "{nick1}, {medicine} టైం అయ్యింది.",
               "{nick3}, ఈరోజు {medicine} మానకు.",
               "{nick2}, ఆరోగ్యం జాగ్రత్త — {medicine} టైం."],
        "hi": ["{nick1}, दवा का समय है 💊 {medicine} ले ली? भूलना मत प्लीज़।",
               "दवाई ली, {nick2}?",
               "{nick1}, {medicine} का समय हो गया।",
               "{nick3}, आज {medicine} मत छोड़ना।",
               "{nick2}, सेहत का ख्याल — {medicine} का समय।"],
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
        "en": ["{nick1}, how's your health today? 🩺 Any pain?",
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


# ── BUTTONS — exact strings matched to Meta-approved templates ─────────────
BUTTONS: dict[str, dict[str, list[tuple[str, str]]]] = {
    # Morning Wish / Mood / Feeling / Goodnight
    "morning_wish": {
        "en": [("Slept well 😴", "feeling:good"), ("So-so 🙂", "feeling:okay"), ("Couldn't sleep 😔", "feeling:not_well")],
        "te": [("బాగున్నాను 😊", "feeling:good"), ("పరవాలేదు 🙂", "feeling:okay"), ("బాగోలేదు 😟", "feeling:not_well")],
        "hi": [("अच्छा 😊", "feeling:good"), ("ठीक है 🙂", "feeling:okay"), ("ठीक नहीं हूँ 😟", "feeling:not_well")],
    },
    "how_feeling": {
        "en": [("Good 😊", "feeling:good"), ("Okay 🙂", "feeling:okay"), ("Not well 😟", "feeling:not_well")],
        "te": [("బాగున్నాను 😊", "feeling:good"), ("పరవాలేదు 🙂", "feeling:okay"), ("బాగోలేదు 😟", "feeling:not_well")],
        "hi": [("अच्छा 😊", "feeling:good"), ("ठीक है 🙂", "feeling:okay"), ("ठीक नहीं हूँ 😟", "feeling:not_well")],
    },
    "goodnight": {
        "en": [("Good day 😊", "feeling:good"), ("Average 🙂", "feeling:okay"), ("Tired 😟", "feeling:not_well")],
        "te": [("బాగున్నాను 😊", "feeling:good"), ("పరవాలేదు 🙂", "feeling:okay"), ("బాగోలేదు 😟", "feeling:not_well")],
        "hi": [("अच्छा 😊", "feeling:good"), ("ठीक है 🙂", "feeling:okay"), ("ठीक नहीं हूँ 😟", "feeling:not_well")],
    },
    "health_check": {
        "en": [("All good 🩺", "feeling:good"), ("Some pain", "feeling:not_well"), ("Bad day 😟", "emergency:health")],
        "te": [("బాగున్నాను 🩺", "feeling:good"), ("నొప్పి 😟", "feeling:not_well"), ("బాలేదు 🚨", "emergency:health")],
        "hi": [("ठीक है 🩺", "feeling:good"), ("दर्द है 😟", "feeling:not_well"), ("खराब 🚨", "emergency:health")],
    },
    # Medicine
    "medicine": {
        "en": [("Done ✅", "done:medicine"), ("Not yet", "pending:medicine"), ("Skipped", "skip:medicine")],
        "te": [("వేసుకున్నా ✅", "done:medicine"), ("ఇంకా లేదు ⏰", "pending:medicine"), ("వేసుకోలేదు ❌", "skip:medicine")],
        "hi": [("ले लिया ✅", "done:medicine"), ("अभी नहीं ⏰", "pending:medicine"), ("छोड़ दिया ❌", "skip:medicine")],
    },
    "water": {
        "en": [("Done 💧", "done:water"), ("Will now", "pending:water"), ("Forgot", "skip:water")],
        "te": [("తాగాను 💧", "done:water"), ("ఇప్పుడు ⏰", "pending:water"), ("మర్చిపోయా ❌", "skip:water")],
        "hi": [("पी लिया 💧", "done:water"), ("अभी ⏰", "pending:water"), ("भूल गई ❌", "skip:water")],
    },
    "bp_check": {
        "en": [("Checked ✅", "done:bp"), ("Not yet", "pending:bp"), ("No machine", "skip:bp")],
        "te": [("చెక్ చేసా ✅", "done:bp"), ("ఇంకా లేదు ⏰", "pending:bp"), ("మెషిన్ లేదు ❌", "skip:bp")],
        "hi": [("चेक किया ✅", "done:bp"), ("अभी नहीं ⏰", "pending:bp"), ("मशीन नहीं ❌", "skip:bp")],
    },
    "sugar_check": {
        "en": [("Checked ✅", "done:sugar"), ("Not yet", "pending:sugar"), ("No machine", "skip:sugar")],
        "te": [("చెక్ చేసా ✅", "done:sugar"), ("ఇంకా లేదు ⏰", "pending:sugar"), ("మెషిన్ లేదు ❌", "skip:sugar")],
        "hi": [("चेक किया ✅", "done:sugar"), ("अभी नहीं ⏰", "pending:sugar"), ("मशीन नहीं ❌", "skip:sugar")],
    },
    # Meals
    "breakfast": {
        "en": [("Had it 🍵", "done:breakfast"), ("Having now", "pending:breakfast"), ("Not hungry", "skip:breakfast")],
        "te": [("తిన్నాను ✅", "done:breakfast"), ("తింటాను ⏰", "pending:breakfast"), ("తినను ❌", "skip:breakfast")],
        "hi": [("मैंने खा लिया ✅", "done:breakfast"), ("खा लेंगे ⏰", "pending:breakfast"), ("नहीं खाना ❌", "skip:breakfast")],
    },
    "lunch": {
        "en": [("Had it 🍽", "done:lunch"), ("Not yet", "pending:lunch"), ("Not hungry", "skip:lunch")],
        "te": [("తిన్నాను ✅", "done:lunch"), ("తింటాను ⏰", "pending:lunch"), ("తినను ❌", "skip:lunch")],
        "hi": [("खा लिया ✅", "done:lunch"), ("बाद में ⏰", "pending:lunch"), ("नहीं खाना ❌", "skip:lunch")],
    },
    "dinner": {
        "en": [("Done 🌙", "done:dinner"), ("Not yet", "pending:dinner"), ("Skipping", "skip:dinner")],
        "te": [("తిన్నాను 🌙", "done:dinner"), ("తింటాను ⏰", "pending:dinner"), ("తినను ❌", "skip:dinner")],
        "hi": [("खा लिया 🌙", "done:dinner"), ("बाद में ⏰", "pending:dinner"), ("नहीं खाना ❌", "skip:dinner")],
    },
    # Routines
    "afternoon_checkin": {
        "en": [("Resting 🛌", "done:rest"), ("Busy", "pending:rest"), ("Not well 😟", "feeling:not_well")],
        "te": [("రెస్ట్ 🛌", "done:rest"), ("బిజీ ⏰", "pending:rest"), ("బాగోలేదు 😟", "feeling:not_well")],
        "hi": [("आराम 🛌", "done:rest"), ("व्यस्त ⏰", "pending:rest"), ("ठीक नहीं 😟", "feeling:not_well")],
    },
    "tea_check": {
        "en": [("Done ☕", "done:tea"), ("Now", "pending:tea"), ("Skipped", "skip:tea")],
        "te": [("తాగాను ☕", "done:tea"), ("ఇప్పుడు ⏰", "pending:tea"), ("లేదు ❌", "skip:tea")],
        "hi": [("पी लिया ☕", "done:tea"), ("अभी ⏰", "pending:tea"), ("नहीं ❌", "skip:tea")],
    },
    "walk_check": {
        "en": [("Done 🚶‍♀️", "done:walk"), ("Later", "pending:walk"), ("Not today", "skip:walk")],
        "te": [("వెళ్ళాను 🚶‍♀️", "done:walk"), ("తర్వాత ⏰", "pending:walk"), ("ఈరోజు లేదు ❌", "skip:walk")],
        "hi": [("हो गया 🚶‍♀️", "done:walk"), ("बाद में ⏰", "pending:walk"), ("आज नहीं ❌", "skip:walk")],
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def render_slot_buttons(category: str, language: str = "en") -> list[tuple[str, str]]:
    slot = BUTTONS.get(category, BUTTONS["how_feeling"])
    return slot.get(language, slot["en"])[:3]


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
    bucket = SLOT_VARIANTS.get(category) or SLOT_VARIANTS.get("how_feeling", {})
    variants = bucket.get(language) or bucket.get("en", ["{nick1}, thinking of you 💛"])
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


async def render_slot_body_async(
    category: str,
    language: str,
    parent: dict,
    day_index: int = 0,
    medicine_name: str = "your medicine",
    variants_per_slot: int = 7,
) -> str:
    bucket = SLOT_VARIANTS.get(category) or SLOT_VARIANTS.get("how_feeling", {})
    variants = bucket.get(language) or bucket.get("en", ["{nick1}, thinking of you 💛"])
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


DEFAULT_EMERGENCY_KEYWORDS = [
    "help", "emergency", "pain", "fell", "fall", "hospital", "chest pain", "breathless", "dizzy",
    "not well", "sick", "so sick",
    "సహాయం", "అత్యవసరం", "నొప్పి", "పడిపోయాను", "పడిపోయా", "ఒంట్లో బాలేదు", "బాలేదు",
    "తల తిరుగుతోంది", "గుండె నొప్పి",
    "मदद", "आपातकाल", "दर्द", "गिर गया", "तबीयत ठीक नहीं", "तबीयत खराब", "सांस नहीं", "सीने में दर्द",
]


def public_categories():
    return [{"key": k, "type": category_type(k)} for k in SLOT_VARIANTS.keys()]