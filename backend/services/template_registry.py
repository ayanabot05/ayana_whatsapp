"""Build payloads from the approved Meta catalog, including actual button indexes."""
import json
import os
import re
from functools import lru_cache
from pathlib import Path


def catalog():
    path = Path(__file__).parents[1] / 'approved_templates.json'
    return _read_catalog(path, path.stat().st_mtime_ns)


@lru_cache(maxsize=1)
def _read_catalog(path, modified_at):
    # Atomic catalog synchronization becomes visible on the next send.
    return json.loads(path.read_text(encoding='utf-8'))


def definition(name, language):
    requested = os.environ.get('WA_TEMPLATE_' + name.upper(), name)
    matches = [row for row in catalog() if row.get('status') == 'APPROVED'
               and row['name'].lstrip('_') == requested.lstrip('_')]
    if not matches:
        raise ValueError(f'Approved WhatsApp template unavailable: {requested}')
    return next((row for row in matches if row['language'] == language), matches[0])


def build(name, language, values, button_payload=None):
    row = definition(name, language)
    body = next((c.get('text', '') for c in row['components'] if c['type'] == 'BODY'), '')
    variables = sorted(set(int(n) for n in re.findall(r'\{\{(\d+)\}\}', body)))
    if variables != list(range(1, len(values) + 1)):
        raise ValueError(f"Template {row['name']} requires {len(variables)} body parameters")
    values = [' '.join(str(value).split()) or '-' for value in values]
    components = []
    if values:
        components.append({'type': 'body', 'parameters': [{'type': 'text', 'text': v} for v in values]})
    if button_payload:
        buttons = next((c.get('buttons', []) for c in row['components'] if c['type'] == 'BUTTONS'), [])
        for index, button in enumerate(buttons):
            if button['type'] == 'QUICK_REPLY':
                components.append({'type': 'button', 'sub_type': 'quick_reply', 'index': str(index),
                                   'parameters': [{'type': 'payload', 'payload': button_payload}]})
                break
    rendered = re.sub(r'\{\{(\d+)\}\}', lambda m: values[int(m[1]) - 1], body)
    return {'name': row['name'], 'language': {'code': row['language']}, 'components': components}, rendered
