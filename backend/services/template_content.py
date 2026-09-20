"""Snapshots of supplied approved parent text; not claims of live approval."""
BODIES = {
 'opener': {'en': "Hi {{1}}! This is AYANA checking in for {{2}}. I'm here for check-ins, reminders, and updates. 💛", 'te': 'నమస్తే {{1}}! AYANA {{2}} కోసం చెక్-ఇన్ చేస్తోంది. ఈరోజు మీరు ఎలా ఉన్నారు?', 'hi': 'नमस्ते {{1}}! AYANA {{2}} के लिए चेक-इन कर रही है। आज आप कैसा महसूस कर रहे हैं?'},
 'medicine': {'en': '💊 {{1}} Time for a {{2}} tablet.', 'te': '⏰{{1}}, మందుల టైం మీ {{2}} టాబ్లెట్ 💊 వేసుకోండి, మర్చిపోకండి!', 'hi': '⏰ {{1}}, दवाई का समय हो गया है। अपनी {{2}} की टैबलेट खा लीजिए, भूलना मत!'},
 'meal': {'en': '🍽 {{1}}, have you eaten? Eat well and rest for some time.', 'te': '🍽️ {{1}}, భోజనం చేశారా?', 'hi': '🍽 {{1}}, खाने का समय! 🍽 अच्छे से खाना, फिर थोड़ा आराम करना।'},
 'mood': {'en': '💬 {{1}} How are you feeling right now? 💛', 'te': '💬 {{1}} ఈరోజు ఎలా ఉన్నారు?', 'hi': '💬 {{1}}, आज कैसा महसूस कर रहे हैं?'},
 'reengagement': {'en': "Hi {{1}}, I haven't heard from you today. Everything okay? Reply whenever you can.", 'te': 'హలో {{1}}, ఈరోజు మీ నుండి రిప్లై రాలేదు. అంతా బాగానే ఉందా? వీలున్నప్పుడు రిప్లై ఇవ్వండి.', 'hi': 'नमस्ते {{1}}, आज आपसे जवाब नहीं मिला। सब ठीक तो है? जब समय हो जवाब दें।'},
 'office_return': {'en': 'Hi {{1}}, did you reach home from office/work? 💼 How was your day? Did you come back safely? 💛', 'te': 'హాయ్ {{1}}, ఆఫీస్/పని నుండి ఇంటికి వచ్చారా? 💼 ఈరోజు పని ఎలా ఉంది? సురక్షితంగా వచ్చారా? 💛', 'hi': 'हाय {{1}}, क्या आप ऑफिस/काम से घर आ गए? 💼 आज काम कैसा रहा? सुरक्षित पहुँचे? 💛'},
 'market_return': {'en': 'Hi {{1}}, did you come back from market safely? 🛒 Did you reach home? How was market? 💛', 'te': 'హాయ్ {{1}}, మార్కెట్ నుండి సురక్షితంగా వచ్చారా? 🛒 ఇంటికి చేరారా? మార్కెట్ ఎలా ఉంది? 💛', 'hi': 'हाय {{1}}, क्या आप बाजार से सुरक्षित आ गए? 🛒 घर पहुँचे? बाजार कैसा रहा? 💛'},
 'shopping_return': {'en': 'Hi {{1}}, did you come back from {{2}} shopping? 🛍️ How was your shopping? Are you home safely? 💛', 'te': 'హాయ్ {{1}}, {{2}} షాపింగ్ నుండి తిరిగి వచ్చారా? 🛍️ షాపింగ్ ఎలా జరిగింది? సురక్షితంగా ఇంటికి చేరారా? 💛', 'hi': 'हाय {{1}}, क्या आप {{2}} शॉपिंग से वापस आ गए? 🛍️ शॉपिंग कैसी रही? सुरक्षित घर पहुँचे? 💛'},
 'temple_return': {'en': 'Hi {{1}}, did you come back from temple? 🛕 How was darshan? Reached home safely? 💛', 'te': 'హాయ్ {{1}}, గుడి నుండి తిరిగి వచ్చారా? 🛕 దర్శనం ఎలా జరిగింది? సురక్షితంగా ఇంటికి చేరారా? 💛', 'hi': 'हाय {{1}}, क्या आप मंदिर से वापस आ गए? 🛕 दर्शन कैसा रहा? सुरक्षित घर पहुँचे? 💛'},
 'outing_return': {'en': 'Hi {{1}}, did you reach home safely? 🏡 Are you back? How was your outing? 💛', 'te': 'హాయ్ {{1}}, సురక్షితంగా ఇంటికి చేరారా? 🏡 ఇంటికి తిరిగి వచ్చారా? బయటకు వెళ్లడం ఎలా ఉంది? 💛', 'hi': 'हाय {{1}}, क्या आप सुरक्षित घर पहुँच गए? 🏡 वापस आ गए? बाहर जाना कैसा रहा? 💛'},
}


def snapshot(kind, language, values):
    text = BODIES.get(kind, {}).get(language, '')
    for key, value in values.items():
        text = text.replace('{{' + str(key) + '}}', str(value))
    return text