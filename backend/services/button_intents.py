"""Classify only within an exactly referenced outbound message."""
import re


def _button_text(value):
    return ' '.join(re.sub(r'[^\w\s]', '', value.lower()).split())


# Exact titles submitted in October 2026. Classification still requires the
# referenced outbound category; a tea answer cannot complete a medicine slot.
SUBMITTED_BUTTONS = {
    'walk_check': [('done', ('Walked', 'నడిచాను', 'टहल लिया')),
                   ('pending', ('Will go later', 'తర్వాత వెళ్తా', 'बाद में')),
                   ('skip', ('Not today', 'ఈరోజు లేదు', 'आज नहीं'))],
    'tea_check': [('done', ('Had it', 'తాగాను', 'पी ली')),
                  ('pending', ('Later', 'తర్వాత', 'बाद में')),
                  ('skip', ('Skip today', 'వద్దు', 'आज नहीं'))],
    'water': [('done', ('Drank', 'తాగాను', 'पी लिया')),
              ('pending', ('Will drink now', 'ఇప్పుడు తాగుతా', 'थोड़ी देर में'))],
}
for _category in ('bp_check', 'sugar_check'):
    SUBMITTED_BUTTONS[_category] = [
        ('done', ('Checked', 'చెక్ చేశాను', 'जाँच लिया')),
        ('pending', ('Will check later', 'తర్వాత చేస్తా', 'बाद में')),
        ('feeling:not_well', ('Feeling unwell', 'బాగోలేదు', 'ठीक नहीं')),
    ]
SUBMITTED_BUTTONS['health_check'] = [
    ('feeling:good', ('All fine', 'బాగున్నా', 'ठीक हूँ')),
    ('feeling:not_well', ('Mild discomfort', 'కొంచెం ఇబ్బంది', 'थोड़ी परेशानी')),
    ('emergency:help', ('Need help', 'సహాయం కావాలి', 'मदद चाहिए')),
]
SUBMITTED_BUTTONS['afternoon_checkin'] = [
    ('feeling:good', ('All good', 'బాగుంది', 'सब ठीक')),
    ('feeling:okay', ('Resting', 'విశ్రాంతి', 'आराम कर रहा')),
    ('feeling:not_well', ('Not well', 'బాగోలేదు', 'ठीक नहीं')),
]
for _category in ('morning_wish', 'goodnight'):
    SUBMITTED_BUTTONS[_category] = [
        ('feeling:not_well', ('Not feeling well', 'బాగోలేదు', 'ठीक नहीं')),
    ]

SAFETY = {'office_return', 'market_return', 'shopping_return', 'temple_return', 'outing_return'}
ALIASES = {'tea': 'tea_check', 'walk': 'walk_check', 'rest': 'afternoon_checkin', 'bp': 'bp_check', 'sugar': 'sugar_check'}


def exact_button_intent(log, payload, title):
    if not log:
        return 'text'
    category = log['category']
    text = (title or '').strip().lower()
    for result, titles in SUBMITTED_BUTTONS.get(category, []):
        if _button_text(text) in {_button_text(t) for t in titles}:
            return result if ':' in result else f'{result}:{category}'
    action, _, target = (payload or '').partition(':')
    if category in SAFETY:
        if any(w in text for w in ('on the way', 'దారిలో', 'रास्ते')):
            return 'on_way:' + category
        if any(w in text for w in ('shopping done', 'darshan done', 'done 🛍', 'దర్శనం', 'షాపింగ్', 'दर्शन', 'शॉपिंग', 'हो गई', 'అయ్యింది')):
            return 'activity_done:' + category
        if any(w in text for w in ('reached', 'home safe', 'yes', 'వచ్చా', 'ఇంటికి', 'సేఫ్', 'అవును', 'సురక్షితంగా', 'पहुँचा', 'पहुँच', 'हाँ', 'सुरक्षित', 'घर आ')):
            return 'arrived:' + category
        return 'text'
    if category == 'reengagement' or log.get('msg_type') == 'reengagement':
        return 'reengagement:reply'
    if action == 'feeling' and category not in ('medicine', 'water', 'bp_check', 'sugar_check'):
        return payload
    if category in ('morning_wish', 'goodnight', 'mood', 'midday_checkin'):
        from whatsapp import parse_reply
        feeling = parse_reply(text)
        if feeling in ('good', 'okay', 'not_well'):
            return 'feeling:' + feeling
    if category in ('breakfast', 'lunch', 'dinner'):
        if text in ('yes', 'తిన్నాను', 'मैंने खा लिया'):
            return 'done:' + category
        if text in ('తింటాను', 'खा लेंगे'):
            return 'pending:' + category
        if text in ('తినను', 'नहीं खाना'):
            return 'skip:' + category
    if action in ('done', 'pending', 'skip') and ALIASES.get(target, target) == category:
        return f'{action}:{category}'
    generic = {'reminder_done': 'done', 'meal_done': 'done', 'reminder_pending': 'pending', 'meal_pending': 'pending', 'reminder_skip': 'skip', 'meal_skip': 'skip'}
    if payload in generic:
        return generic[payload] + ':' + category
    for words, result in [
        (('not yet', 'later', 'will now', 'ఇంకా', 'తర్వాత', 'अभी नहीं', 'बाद में'), 'pending'),
        (('skipped', 'skip', 'not hungry', 'లేదు', 'छोड़'), 'skip'),
        (('taken', 'done', 'had it', 'checked', 'వేసుకున్నా', 'తిన్నా', 'అయింది', 'ले लिया', 'हो गया', 'कर लिया'), 'done'),
    ]:
        if any(w in text for w in words):
            return result + ':' + category
    return 'text'
