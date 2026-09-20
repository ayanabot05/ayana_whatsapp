"""Only family-supplied prescription data; never infer a dose or appearance."""
WORDS = {
    'te': {'white':'తెలుపు','yellow':'పసుపు','red':'ఎరుపు','blue':'నీలం','green':'ఆకుపచ్చ','pink':'గులాబీ','round':'గుండ్రంగా','oval':'అండాకారం','capsule':'క్యాప్సూల్ ఆకారం','before_food':'భోజనానికి ముందు','after_food':'భోజనం తర్వాత','with_food':'భోజనంతో','empty_stomach':'ఖాళీ కడుపుతో'},
    'hi': {'white':'सफेद','yellow':'पीला','red':'लाल','blue':'नीला','green':'हरा','pink':'गुलाबी','round':'गोल','oval':'अंडाकार','capsule':'कैप्सूल आकार','before_food':'खाने से पहले','after_food':'खाने के बाद','with_food':'खाने के साथ','empty_stomach':'खाली पेट'},
}


def medicine_description(medicine, language='en'):
    terms = WORDS.get(language, {})
    details = []
    for key in ('dose', 'color', 'shape', 'timing', 'notes'):
        value = medicine.get(key)
        if value:
            details.append(' '.join(terms.get(value, str(value).replace('_', ' ')).split()))
    return medicine['name'] + (' (' + '; '.join(details) + ')' if details else '')