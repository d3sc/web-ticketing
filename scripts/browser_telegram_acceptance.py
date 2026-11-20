"""Real Chromium + isolated MySQL; Telegram transport is explicitly MOCKED."""
import json
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://helpdesk.test:5018'
CONTAINER = 'web-ticketing-telegram-browser'
out = Path('verification/telegram')
out.mkdir(parents=True, exist_ok=True)
checks = []


def db_action(action='inspect'):
    code = '''import json,os
from sqlalchemy.engine import make_url
from helpdesk import create_app,db
from helpdesk.models import TelegramOutbox,Ticket
from helpdesk import telegram as tg
u=make_url(os.environ['DATABASE_URL']); assert u.database=='helpdesk_test' and u.host=='test-db'
app=create_app({'TELEGRAM_BOT_TOKEN':'fixture-not-real','APP_BASE_URL':'http://helpdesk.test:5018'})
with app.app_context():
    payloads=[]
    def fake(token,payload):
        payloads.append(payload)
        return {'ok':False,'error_code':503} if ACTION=='fail' else {'ok':True,'result':{'message_id':101}}
    tg._transport=fake
    if ACTION!='inspect': tg.process_outbox()
    db.session.remove()
    rows=[dict(id=r.id,ticket_id=r.ticket_id,text=r.text,url=r.url,state=r.state,attempts=r.attempts,error=r.last_error) for r in db.session.scalars(db.select(TelegramOutbox).order_by(TelegramOutbox.id))]
    print(json.dumps({'rows':rows,'payloads':payloads,'tickets':db.session.scalar(db.select(db.func.count(Ticket.id)))}))
'''.replace('ACTION', repr(action))
    return json.loads(subprocess.check_output(['docker', 'exec', '-i', CONTAINER, 'python', '-c', code], text=True))

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--host-resolver-rules=MAP helpdesk.test 127.0.0.1', '--no-proxy-server'])
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))

    def login(name):
        page.goto(BASE + '/login')
        page.locator('#email').fill(name + '@example.test')
        page.locator('#password').fill('Test-password-123')
        page.get_by_role('button', name='Masuk', exact=True).click()
        expect(page).to_have_url(BASE + ('/' if name in ('employee', 'other') else '/tickets'))

    def logout():
        page.get_by_role('button', name='Keluar', exact=True).click()

    def post(path, data):
        token = page.locator('[name=csrf_token]').first.input_value()
        return page.evaluate('''async ({path,data,token}) => {
          const r=await fetch(path,{method:'POST',body:new URLSearchParams({...data,csrf_token:token})});
          return r.status;
        }''', {'path': path, 'data': data, 'token': token})

    def create(title):
        page.goto(BASE + '/tickets/new')
        page.locator('#title').fill(title)
        page.locator('#description').fill('Uji browser terisolasi, bukan tiket operasional.')
        page.locator('#category_id').select_option(label='Jaringan')
        page.locator('#priority').select_option('high')
        page.locator('form').filter(has=page.locator('#title')).locator('button').click()
        tid = int(page.url.rsplit('/', 1)[1])
        return tid

    login('admin')
    page.get_by_role('link', name='Notifikasi Telegram', exact=True).click()
    page.locator('#enabled').check()
    page.locator('#chat_id').fill('-100123456789')
    page.get_by_role('button', name='Simpan Pengaturan', exact=True).click()
    expect(page.get_by_text('Pengaturan Telegram berhasil disimpan.', exact=True)).to_be_visible()
    page.reload()
    expect(page.locator('#enabled')).to_be_checked()
    expect(page.locator('#chat_id')).to_have_value('-100123456789')
    page.get_by_role('button', name='Kirim Pesan Tes', exact=True).click()
    expect(page.get_by_text('Pesan tes berhasil dikirim ke Chat ID Tujuan yang tersimpan.', exact=True)).to_be_visible()
    checks.append('Admin saves negative group destination and toggle in MySQL; test message success via mocked Telegram')
    for width, label in [(1440, 'desktop'), (390, 'mobile')]:
        page.set_viewport_size({'width': width, 'height': 1000})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(out / ('settings-' + label + '.png')), full_page=True)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    logout()
    before = len(db_action()['rows'])
    for name in ['employee', 'agent']:
        login(name)
        assert page.goto(BASE + '/admin/settings/telegram').status == 403
        assert post('/admin/settings/telegram', {'enabled':'y','chat_id':'111'}) == 403
        assert post('/admin/settings/telegram/test', {}) == 403
        logout()
    checks.append('Employee and IT agent: settings GET, settings POST and test POST denied with 403')
    login('employee')
    tid = create('Uji Telegram tiket baru')
    rows = db_action()['rows']
    assert len(rows) == before + 1
    row = rows[-1]
    assert row['state'] == 'pending' and row['attempts'] == 0
    assert row['ticket_id'] == tid
    result = db_action('send')
    assert result['rows'][-1]['state'] == 'sent'
    payload = result['payloads'][-1]
    assert all(t in payload['text'] for t in ['Tiket baru masuk', f'IT-{tid:06d}', 'Uji Telegram tiket baru', 'Jaringan', 'Tinggi', 'WIB'])
    link = payload['reply_markup']['inline_keyboard'][0][0]
    assert link['text'] == 'Buka Tiket' and link['url'] == BASE + f'/tickets/{tid}'
    assert link['url'] in payload['text']
    page.goto(link['url'])
    expect(page.locator('h1')).to_contain_text('Uji Telegram tiket baru')
    page.locator('#body').fill('Balasan tidak mengirim alert baru')
    page.get_by_role('button', name='Kirim Balasan', exact=True).click()
    logout()
    assert page.goto(link['url']).url == BASE + '/login?next=%2Ftickets%2F' + str(tid) or '/login' in page.url
    login('other')
    assert page.goto(link['url']).status == 403
    logout()
    login('agent')
    page.goto(link['url'])
    page.get_by_role('button', name='Ambil Tiket', exact=True).click()
    page.locator('#body').fill('Agen membalas tanpa alert baru')
    page.get_by_role('button', name='Kirim Balasan', exact=True).click()
    form = page.locator('form[action$="/update"]')
    form.locator('[name=status]').select_option('in_progress')
    form.locator('[name=priority]').select_option('low')
    form.locator('button').click()
    assert len(db_action()['rows']) == before + 1
    assert db_action('send')['payloads'] == []
    checks.append('Only ticket creation queues one committed alert; Indonesian summary, WIB and Buka Tiket link verified; replies, claim, priority/status updates enqueue nothing')
    checks.append('Absolute button/fallback URL opens ticket; anonymous requires login and other employee receives 403 (local browser hostname mapping, NOT connected VPN device)')
    logout()
    login('employee')
    failed_tid = create('Uji Telegram layanan gagal')
    result = db_action('fail')
    assert result['rows'][-1]['ticket_id'] == failed_tid
    assert result['rows'][-1]['state'] == 'pending' and result['rows'][-1]['attempts'] == 1
    assert result['rows'][-1]['error']
    assert page.goto(BASE + f'/tickets/{failed_tid}').status == 200
    checks.append('Mocked Telegram 503 records failure/retry; ticket creation and saved ticket remain available')
    assert not errors
    browser.close()
report = {'browser':'Playwright Chromium', 'database':'isolated MySQL helpdesk_test', 'telegram':'MOCKED; live delivery unverified', 'vpn_device_link':'unverified', 'checks':checks, 'page_errors':errors}
(out / 'browser-results.json').write_text(json.dumps(report, indent=2) + '\n')
for check in checks:
    print('PASS:', check)
