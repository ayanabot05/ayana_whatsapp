"""Classify only within an exactly referenced outbound message."""
SAFETY = {'office_return', 'market_return', 'shopping_return', 'temple_return', 'outing_return'}
ALIASES = {'tea': 'tea_check', 'walk': 'walk_check', 'rest': 'afternoon_checkin', 'bp': 'bp_check', 'sugar': 'sugar_check'}


def exact_button_intent(log, payload, title):
    if not log:
        return 'text'
    category = log['category']
    text = (title or '').strip().lower()
    action, _, target = (payload or '').partition(':')
    if category in SAFETY:
        if any(w in text for w in ('on the way', 'దారిలో', 'रास्ते')):
            return 'on_way:' + category
        if any(w in text for w in ('shopping done', 'darshan done', 'done 🛍', 'దర్శనం', 'షాపింగ్', 'दर्शन', 'शॉपिंग', 'हो गई', 'అయ్యింది')):
            return 'activity_done:' + category
        if any(w in text for w in ('reached', 'home safe', 'yes', 'వచ్చా', 'ఇంటికి', 'సేఫ్', 'అవును', 'पहुँचा', 'हाँ', 'सुरक्षित')):
            return 'arrived:' + category
        return 'text'
    if category == 'reengagement' or log.get('msg_type') == 'reengagement':
        return 'reengagement:reply'
    if action == 'feeling' and category not in ('medicine', 'water', 'bp_check', 'sugar_check'):
        return payload
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