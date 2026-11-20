"""Read-only deployed-source/UI verification; no live account/ticket/settings mutations."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[1]
os.chdir(root)
files = [str(p.relative_to(root)) for p in (root / 'helpdesk').rglob('*') if p.is_file() and p.suffix in ('.py', '.html', '.css')]
code = 'import json,pathlib,hashlib; print(json.dumps({p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in ' + repr(files) + '}))'
remote = json.loads(subprocess.check_output(['docker', 'compose', 'exec', '-T', 'web', 'python', '-c', code], text=True))
local = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in files}
assert remote == local, 'Deployed code does not match working checkout'
creds = json.loads((root / '.local-credentials').read_text())
base = 'http://127.0.0.1:5017'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    assert page.goto(base + '/health').json() == {'status': 'ok'}
    assert '/login' in page.goto(base + '/admin/settings/telegram').url
    page.locator('#email').fill(creds['email'])
    page.locator('#password').fill(creds['password'])
    page.get_by_role('button', name='Masuk', exact=True).click()
    expect(page).to_have_url(base + '/tickets')
    page.get_by_role('link', name='Notifikasi Telegram', exact=True).click()
    expect(page.get_by_role('heading', name='Notifikasi Telegram', exact=True)).to_be_visible()
    expect(page.locator('#enabled')).not_to_be_checked()
    expect(page.locator('#chat_id')).to_have_value('')
    expect(page.get_by_text('Belum ada antrean notifikasi.', exact=True)).to_be_visible()
    expect(page.get_by_text('Token bot:', exact=False).first).to_be_visible()
    browser.close()
report = {'live_url': base, 'deployed_sources_match_checkout': True, 'health': 'ok',
          'admin_login': 'passed', 'anonymous_settings_requires_login': True,
          'telegram_settings_page': 'passed', 'default_disabled': True, 'live_mutations': 'none except login',
          'live_telegram_delivery': 'unverified: bot token and destination unavailable',
          'connected_vpn_device_link': 'unverified: no connected recipient device available'}
out = root / 'verification/telegram'
(out / 'live-smoke.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
