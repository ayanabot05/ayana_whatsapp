"""Refresh the local catalog from Meta. Does not submit templates or send messages."""
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / 'backend' / '.env')
    token = os.environ.get('META_WA_ACCESS_TOKEN')
    account = os.environ.get('META_WA_BUSINESS_ACCOUNT_ID')
    if not token or not account:
        raise SystemExit('META_WA_ACCESS_TOKEN and META_WA_BUSINESS_ACCOUNT_ID are required.')
    version = os.environ.get('META_WA_GRAPH_VERSION', 'v22.0')
    url = f'https://graph.facebook.com/{version}/{account}/message_templates'
    params = {'fields': 'name,status,category,language,components', 'limit': 100}
    rows = []
    try:
        with httpx.Client(timeout=25) as client:
            while True:
                response = client.get(url, headers={'Authorization': f'Bearer {token}'}, params=params)
                if response.status_code != 200:
                    raise SystemExit(f'Meta returned HTTP {response.status_code}; local catalog preserved.')
                data = response.json()
                rows.extend(data['data'])
                if not data.get('paging', {}).get('next'):
                    break
                params['after'] = data['paging']['cursors']['after']
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise SystemExit(f'Catalog refresh failed ({type(exc).__name__}); local catalog preserved.') from None
    if not rows:
        raise SystemExit('Meta returned no templates; local catalog preserved.')
    target = ROOT / 'backend' / 'approved_templates.json'
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(target)
    approved = {row['name'].lstrip('_') for row in rows if row['status'] == 'APPROVED'}
    expected = []
    for filename in ('daily_template_drafts.json', 'supplied_warning_welcome_templates.json', 'delivery_issue_templates.json', 'voice_summary_templates.json', 'monthly_pdf_templates.json'):
        expected.extend(row['name'] for row in json.loads((ROOT / 'docs' / filename).read_text(encoding='utf-8')))
    expected.extend(row['name'].lstrip('_') for row in json.loads(
        (ROOT / 'docs' / 'meta_template_snapshot.json').read_text(encoding='utf-8')))
    print(f'Refreshed {len(rows)} templates from the configured Meta account.')
    missing = sorted(set(expected) - approved)
    if missing:
        print('Still missing approved definitions:')
        print('\n'.join(missing))
    print('Running workers load the updated catalog on their next send.')
    if missing:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
