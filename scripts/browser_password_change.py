"""Password-management browser verification against the isolated MySQL test service only.
Start the migrated tests image with Gunicorn on localhost:5018 after running pytest.
Uses fixture accounts in helpdesk_test; never runs against the live helpdesk service.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:5018'
OLD = 'Test-password-123'
NEW = 'Password-browser-2026!'
output = Path('verification/password-change')
output.mkdir(parents=True, exist_ok=True)
checks = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))

    def login(name, password, succeeds=True):
        page.goto(BASE + '/login')
        page.locator('#email').fill(name + '@example.test')
        page.locator('#password').fill(password)
        page.get_by_role('button', name='Masuk', exact=True).click()
        expect(page).to_have_url(BASE + ('/' if name == 'employee' else '/tickets') if succeeds else BASE + '/login')
        if not succeeds:
            expect(page.get_by_text('Email atau kata sandi salah, atau akun tidak aktif.', exact=True)).to_be_visible()

    def logout():
        page.get_by_role('button', name='Keluar', exact=True).click()
        expect(page).to_have_url(BASE + '/login')

    login('admin', OLD)
    page.goto(BASE + '/admin/users')
    paths = {}
    for name in ['employee', 'agent', 'admin']:
        card = page.locator('form.card').filter(has=page.get_by_text(name + '@example.test', exact=True))
        paths[name] = card.get_by_role('link', name='Ganti Password').get_attribute('href')
    checks.append('Password actions available for employee, IT agent and administrator')
    for name in ['employee', 'agent', 'admin']:
        page.goto(BASE + paths[name])
        expect(page.get_by_role('heading', name='Ganti Password', exact=True)).to_be_visible()
        if name == 'employee':
            for width, label in [(1440, 'desktop'), (390, 'mobile')]:
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / (label + '.png')), full_page=True)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            token = page.locator('form.card [name=csrf_token]').input_value()
            assert context.request.post(BASE + paths[name], form={'current_password': OLD, 'password': NEW, 'confirm_password': NEW}).status == 400
            for data, text in [
                ({'current_password': 'incorrect', 'password': NEW, 'confirm_password': NEW}, 'Password administrator saat ini tidak sesuai.'),
                ({'current_password': OLD, 'password': NEW, 'confirm_password': 'Mismatch-password'}, 'Konfirmasi password tidak sama.'),
                ({'current_password': OLD, 'password': 'short', 'confirm_password': 'short'}, 'Password harus terdiri dari 12–128 karakter.'),
            ]:
                result = context.request.post(BASE + paths[name], form={**data, 'csrf_token': token})
                assert result.status == 400
                assert text in result.text()
            checks.append('CSRF, wrong current admin password, short password and confirmation mismatch rejected')
        page.locator('#current_password').fill(OLD)
        page.locator('#password').fill(NEW)
        page.locator('#confirm_password').fill(NEW)
        page.get_by_role('button', name='Simpan Password', exact=True).click()
        expect(page).to_have_url(BASE + '/admin/users')
        expect(page.get_by_text('Password berhasil diubah.', exact=True)).to_be_visible()
        logout()
        login(name, OLD, succeeds=False)
        login(name, NEW)
        if name != 'admin':
            assert page.goto(BASE + paths[name]).status == 403
            token = page.locator('[name=csrf_token]').first.input_value()
            assert context.request.post(BASE + paths[name], form={'csrf_token': token, 'current_password': NEW, 'password': OLD, 'confirm_password': OLD}).status == 403
        logout()
        checks.append(f'{name}: password changed via browser; old login rejected, new login works' + ('; non-admin GET/POST denied' if name != 'admin' else ''))
        if name != 'admin':
            login('admin', OLD)
    assert not errors, errors
    browser.close()
report = {'base_url': BASE, 'database': 'isolated MySQL helpdesk_test', 'checks': checks, 'page_errors': errors}
(output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
for check in checks:
    print('PASS:', check)
print('Browser page errors:', len(errors))
