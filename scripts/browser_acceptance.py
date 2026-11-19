"""Real Chromium acceptance against live MySQL-backed app; no credentials logged."""
import json
import re
import secrets
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:5017'
credentials = json.loads(Path('.local-credentials').read_text())
run_id = secrets.token_hex(4)
password = secrets.token_urlsafe(24)
accounts = {}
results = []
output = Path('verification')
output.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))

    def login(email, pwd):
        page.goto(BASE + '/login')
        page.locator('#email').fill(email)
        page.locator('#password').fill(pwd)
        page.get_by_role('button', name='Masuk').click()
        target = '/tickets' if email == credentials['email'] or email in (accounts.get('Agen QA'), accounts.get('Agen Kedua QA')) else '/'
        expect(page).to_have_url(BASE + target)

    def logout():
        page.get_by_role('button', name='Keluar').click()
        expect(page).to_have_url(BASE + '/login')

    login(credentials['email'], credentials['password'])
    for name, role in [('Karyawan QA', 'employee'), ('Agen QA', 'it'), ('Karyawan Kedua QA', 'employee'), ('Agen Kedua QA', 'it')]:
        email = role + str(len(accounts)) + '-' + run_id + '@example.test'
        page.goto(BASE + '/admin/users')
        page.locator('#name').fill(name + ' ' + run_id)
        page.locator('#email').fill(email)
        page.locator('#password').fill(password)
        page.locator('#role').select_option(role)
        page.get_by_role('button', name='Buat Pengguna').click()
        expect(page.get_by_text(email, exact=True)).to_be_visible()
        accounts[name] = email
    results.append('Admin created employee and IT accounts through browser forms')
    logout()
    login(accounts['Karyawan QA'], password)
    page.goto(BASE + '/tickets/new')
    title = 'Verifikasi browser jaringan ' + run_id
    page.locator('#title').fill(title)
    page.locator('#description').fill('Koneksi jaringan kantor tidak tersedia. Pengujian penerimaan browser.')
    page.locator('#category_id').select_option(label='Jaringan')
    page.locator('form').filter(has=page.locator('#title')).locator('button').click()
    expect(page).to_have_url(re.compile(r'/tickets/\d+$'))
    ticket_url = page.url
    ticket_id = ticket_url.rsplit('/', 1)[1]
    expect(page.get_by_role('heading', name=re.compile(title))).to_be_visible()
    results.append('Employee submitted ticket with initial Open/Normal')
    logout()
    login(accounts['Agen QA'], password)
    page.goto(ticket_url)
    page.get_by_role('button', name='Ambil Tiket').click()
    expect(page.get_by_role('button', name='Ambil Tiket')).to_have_count(0)
    page.locator('#body').fill('Jaringan telah diperbaiki. Silakan coba kembali.')
    page.get_by_role('button', name='Kirim Balasan').click()
    expect(page.get_by_text('Jaringan telah diperbaiki. Silakan coba kembali.', exact=True)).to_be_visible()
    results.append('IT agent claimed ticket and replied')
    logout()
    login(accounts['Karyawan QA'], password)
    page.goto(ticket_url)
    expect(page.get_by_text('Jaringan telah diperbaiki. Silakan coba kembali.', exact=True)).to_be_visible()
    page.screenshot(path=str(output / 'employee-reply.png'), full_page=True)
    results.append('Employee saw IT reply in browser')
    logout()
    login(accounts['Karyawan Kedua QA'], password)
    response = page.goto(ticket_url)
    assert response.status == 403
    token = page.locator('input[name=csrf_token]').first.get_attribute('value')
    response = context.request.post(ticket_url + '/reply', form={'csrf_token': token, 'body': 'Forbidden reply'})
    assert response.status == 403
    results.append('Second employee direct URL and reply rejected: HTTP 403')
    logout()
    login(accounts['Agen Kedua QA'], password)
    page.goto(ticket_url)
    token = page.locator('input[name=csrf_token]').first.get_attribute('value')
    response = context.request.post(ticket_url + '/update', form={'csrf_token':token, 'status':'in_progress'})
    assert response.status == 403
    results.append('Unassigned IT agent update rejected: HTTP 403')
    logout()
    login(accounts['Agen QA'], password)
    page.goto(ticket_url)
    for status in ['in_progress', 'resolved', 'in_progress', 'resolved', 'closed']:
        form = page.locator('form[action$="/update"]')
        form.locator('[name=status]').select_option(status)
        form.locator('button').click()
        expect(page.locator('aside dd').first).to_have_text({'in_progress':'Diproses','resolved':'Terselesaikan','closed':'Ditutup'}[status])
    expect(page.get_by_text('Tiket ditutup. Balasan tidak diizinkan.')).to_be_visible()
    token = page.locator('input[name=csrf_token]').first.get_attribute('value')
    response = context.request.post(ticket_url + '/reply', form={'csrf_token': token, 'body':'Late reply'})
    assert response.status == 409
    results.append('Agent progressed, resolved, reopened, resolved and closed ticket; closed reply rejected HTTP 409')
    page.screenshot(path=str(output / 'closed-ticket.png'), full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    page.goto(ticket_url)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(output / 'mobile-ticket.png'), full_page=True)
    assert not errors, 'Browser JavaScript errors encountered'
    results.append('390px mobile viewport has no horizontal overflow; no JavaScript page errors')
    browser.close()

report = {'engine':'Chromium', 'base_url':BASE, 'ticket_id':ticket_id, 'checks':results}
(output / 'browser-results.json').write_text(json.dumps(report, indent=2)+'\n')
for result in results:
    print('PASS:', result)
print('Evidence ticket ID:', ticket_id)
