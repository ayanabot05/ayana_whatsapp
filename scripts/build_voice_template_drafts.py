"""Save proposed template definitions; does not contact Meta or mark approval."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
texts = {
    'en': "AYANA care update: {{1}} sent a voice note about {{2}}.\n\nReceived at: {{3}}\n\nAI-generated summary in English:\n{{4}}\n\nThis summary may miss details. Listen to the original recording using the accompanying voice-note notification.",
    'te': "AYANA సమాచారం: {{1}} {{2}} గురించి వాయిస్ మెసేజ్ పంపారు.\n\nఅందిన సమయం: {{3}}\n\nAI రూపొందించిన తెలుగు సారాంశం:\n{{4}}\n\nఈ సారాంశంలో కొన్ని వివరాలు తప్పిపోవచ్చు. అసలు రికార్డింగ్ వినడానికి వాయిస్ మెసేజ్ నోటిఫికేషన్‌ను ఉపయోగించండి.",
    'hi': "AYANA अपडेट: {{1}} ने {{2}} के बारे में एक वॉइस मैसेज भेजा है।\n\nमिलने का समय: {{3}}\n\nAI द्वारा तैयार हिंदी सारांश:\n{{4}}\n\nइस सारांश में कुछ विवरण छूट सकते हैं। मूल रिकॉर्डिंग सुनने के लिए साथ भेजी गई वॉइस मैसेज सूचना का उपयोग करें।",
}
rows = [{'name':f'ayana_parent_voice_summary_{lang}','language':lang,'status':'DRAFT','category':'UTILITY','components':[{'type':'BODY','text':body}]} for lang,body in texts.items()]
(root/'docs/voice_summary_templates.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
reports = {
    'en': "{{1}}'s AYANA monthly report for {{2}} is attached.",
    'te': '{{1}} కోసం {{2}} నెల AYANA నివేదిక జతచేయబడింది.',
    'hi': '{{1}} की {{2}} की AYANA मासिक रिपोर्ट संलग्न है।',
}
rows = [{'name':f'ayana_monthly_report_pdf_{lang}','language':lang,'status':'DRAFT','category':'UTILITY','components':[{'type':'HEADER','format':'DOCUMENT'},{'type':'BODY','text':body}]} for lang,body in reports.items()]
(root/'docs/monthly_pdf_templates.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Saved voice-summary and document-header report drafts. Approval is not implied.')
