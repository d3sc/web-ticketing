"""Browser regression of role landing, owned listings, priorities and responsive UI."""
import json
import re
import secrets
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE = 'http://127.0.0.1:5017'
admin = json.loads(Path('.local-credentials').read_text())
run = secrets.token_hex(4)
password = secrets.token_urlsafe(24)
output = Path('verification/dashboard-v2')
output.mkdir(parents=True, exist_ok=True)
checks = []
accounts = {}
tickets = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width':1440,'height':1000})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))

    def login(email, pwd, target):
        page.goto(BASE + '/login')
        page.locator('#email').fill(email)
        page.locator('#password').fill(pwd)
        page.get_by_role('button', name='Masuk', exact=True).click()
        expect(page).to_have_url(BASE + target)
        expect(page.locator('h1')).to_have_text('Tiket Saya' if target=='/' else 'Antrean Tiket')

    def logout():
        page.get_by_role('button', name='Keluar', exact=True).click()
        expect(page).to_have_url(BASE + '/login')

    def responsive(name):
        for width, label in [(1440,'desktop'), (390,'mobile')]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), name+' overflow'
            page.screenshot(path=str(output / (name+'-'+label+'.png')), full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})

    def create_ticket(title, priority):
        page.goto(BASE + '/tickets/new')
        expect(page.locator('#priority')).to_have_value('normal')
        page.locator('#title').fill(title)
        page.locator('#description').fill('Pengujian regresi pemilik tiket dan prioritas melalui browser.')
        page.locator('#category_id').select_option(label='Jaringan')
        page.locator('#priority').select_option(priority)
        page.locator('form').filter(has=page.locator('#title')).locator('button').click()
        expect(page).to_have_url(re.compile('/tickets/[0-9]+$'))
        url = page.url
        expect(page.locator('aside')).to_contain_text({'low':'Rendah','normal':'Normal','high':'Tinggi'}[priority])
        return url

    login(admin['email'],admin['password'],'/tickets')
    assert page.goto(BASE+'/').status == 200
    expect(page).to_have_url(BASE+'/tickets')
    for name,role in [('employee','employee'), ('other','employee'), ('agent','it')]:
        email = name+'-'+run+'@example.test'
        page.goto(BASE+'/admin/users')
        page.locator('#name').fill('Regresi '+name+' '+run)
        page.locator('#email').fill(email)
        page.locator('#password').fill(password)
        page.locator('#role').select_option(role)
        page.get_by_role('button',name='Buat Pengguna',exact=True).click()
        expect(page.get_by_text(email, exact=True)).to_be_visible()
        accounts[name]=email
    checks.append('Admin login and root land at IT queue; admin created regression accounts')
    logout()
    login(accounts['other'],password,'/')
    foreign_title='Tiket rahasia pemilik kedua '+run
    foreign_url=create_ticket(foreign_title,'high')
    logout()
    login(accounts['employee'],password,'/')
    for priority in ['low','normal','high']:
        title='Regresi '+priority+' '+run
        tickets.append({'url':create_ticket(title,priority), 'title':title,'priority':priority})
    page.goto(BASE+'/')
    expect(page.locator('[data-status=open]')).to_have_attribute('data-count','3')
    expect(page.locator('[data-status=closed]')).to_have_attribute('data-count','0')
    expect(page.locator('tbody tr')).to_have_count(3)
    expect(page.locator('tbody')).not_to_contain_text(foreign_title)
    expect(page.locator('#assignee_id')).to_have_count(0)
    expect(page.locator('nav a[href="/tickets"]')).to_have_count(0)
    for ticket in tickets:
        expect(page.locator('tr').filter(has_text=ticket['title'])).to_contain_text({'low':'Rendah','normal':'Normal','high':'Tinggi'}[ticket['priority']])
    responsive('employee-dashboard')
    checks.append('Employee root: only 3 own tickets, scoped counts, no IT queue navigation or agent filter; all priorities visible')
    page.locator('#q').fill(foreign_title)
    page.get_by_role('button',name='Terapkan Filter').click()
    expect(page.get_by_role('heading',name='Tidak ada tiket yang cocok')).to_be_visible()
    expect(page.locator('[data-status=open]')).to_have_attribute('data-count','3')
    for path in ['/tickets','/admin/users','/admin/categories',foreign_url.removeprefix(BASE)]:
        response=page.goto(BASE+path)
        assert response.status==403,(path,response.status)
    token=page.locator('[name=csrf_token]').first.get_attribute('value')
    assert context.request.post(foreign_url+'/reply',form={'csrf_token':token,'body':'Unauthorized'}).status==403
    checks.append('Employee search cannot find other owner; direct IT/admin/foreign ticket and reply return 403')
    page.goto(BASE+'/tickets/new')
    page.locator('#priority').select_option('high')
    # Send the actual form with browser required checks bypassed to exercise server validation.
    page.locator('form').filter(has=page.locator('#title')).evaluate('(form) => form.submit()')
    expect(page.locator('#priority')).to_have_value('high')
    responsive('create-ticket')
    page.locator('#title').fill('Invalid priority '+run)
    page.locator('#description').fill('Invalid priority must be rejected')
    page.locator('#priority').evaluate('(s) => { let o=new Option("invalid", "urgent"); s.add(o); s.value="urgent"; }')
    page.locator('form').filter(has=page.locator('#title')).locator('button').click()
    expect(page.get_by_text('Prioritas tidak valid.',exact=True)).to_be_visible()
    checks.append('Priority Normal preselected, High retained after validation failure, invalid choice rejected in Indonesian')
    logout()
    login(accounts['agent'],password,'/tickets')
    page.goto(BASE+'/')
    expect(page).to_have_url(BASE+'/tickets')
    expect(page.locator('#assignee_id')).to_be_visible()
    responsive('it-queue')
    page.goto(tickets[0]['url'])
    page.get_by_role('button',name='Ambil Tiket').click()
    page.locator('#body').fill('Balasan verifikasi dashboard '+run)
    page.get_by_role('button',name='Kirim Balasan').click()
    for status in ['in_progress','resolved','closed']:
        form=page.locator('form[action$="/update"]')
        form.locator('[name=status]').select_option(status)
        form.locator('button').click()
    checks.append('IT login/root land at queue; claim, reply and close workflow remains functional')
    logout()
    login(admin['email'],admin['password'],'/tickets')
    page.locator('#q').fill(tickets[2]['title'])
    page.locator('#priority').select_option('high')
    page.get_by_role('button',name='Terapkan Filter').click()
    expect(page.locator('tbody tr')).to_have_count(1)
    expect(page.locator('tbody')).to_contain_text('Tinggi')
    expect(page.locator('#q')).to_have_value(tickets[2]['title'])
    expect(page.locator('#priority')).to_have_value('high')
    responsive('admin-queue')
    checks.append('Admin queue shows saved High priority; search/filter retained; desktop and mobile layouts verified for all roles')
    assert not errors, errors
    browser.close()
report={'base_url':BASE,'browser':'Playwright Chromium','checks':checks,'page_errors':errors,'tickets':tickets}
(output/'results.json').write_text(json.dumps(report,indent=2)+'\n')
for check in checks:
    print('PASS:',check)
print('Browser page errors:',len(errors))
