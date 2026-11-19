from bs4 import BeautifulSoup
from helpdesk import db
from helpdesk.models import Ticket, TicketEvent


def test_all_pages_and_local_assets(app, client, signin, ticket):
    for name in ('employee','agent','admin'):
        signin(name)
        paths = ['/', '/tickets/new', f'/tickets/{ticket}']
        if name != 'employee':
            paths.append('/tickets')
        if name=='admin':
            paths += ['/admin/users','/admin/categories']
        app.config['WTF_CSRF_ENABLED'] = True
        for path in paths:
            response = client.get(path, follow_redirects=True)
            assert response.status_code == 200, (name,path)
            soup = BeautifulSoup(response.data,'html.parser')
            assert soup.html['lang']=='id'
            for form in soup.select('form[method=post]'):
                assert form.select_one('input[name=csrf_token]'), path
        app.config['WTF_CSRF_ENABLED'] = False
    assert client.get('/static/fallback.css').status_code == 200
    assert client.get('/static/app.css').status_code == 200
    assert client.get('/health').json == {'status':'ok'}


def test_reference_filters_and_real_pagination(app,client,signin,ticket):
    signin('employee')
    assert b'WiFi lantai dua' in client.get(f'/?q=IT-{ticket:06d}').data
    with app.app_context():
        original = db.session.get(Ticket,ticket)
        for i in range(25):
            db.session.add(Ticket(title=f'Pagination {i}',description='Test',creator_id=original.creator_id,category_id=original.category_id))
        db.session.commit()
    for page in (1,2):
        response = client.get(f'/?page={page}&status=open')
        assert response.status_code==200
        soup=BeautifulSoup(response.data,'html.parser')
        assert len(soup.select('tbody tr')) == (20 if page==1 else 6)
        assert soup.select_one('nav[aria-label="Navigasi halaman tiket"] a')
    assert b'WiFi lantai dua' not in client.get('/?q=%25').data


def test_dashboard_ownership_and_initial_priority(app, client, signin, ticket):
    signin('employee')
    assert b'WiFi lantai dua' in client.get('/').data
    assert b'name="priority"' in client.get('/tickets/new').data
    with app.app_context():
        category_id = db.session.get(Ticket, ticket).category_id
    response = client.post('/tickets/new', data={'title': 'Selected high', 'description': 'Test', 'category_id': category_id, 'priority': 'high'})
    assert response.status_code == 302
    assert client.post('/tickets/new', data={'title': 'Invalid', 'description': 'Test', 'category_id': category_id, 'priority': 'invalid'}).status_code == 400
    with app.app_context():
        assert db.session.scalar(db.select(Ticket).where(Ticket.title == 'Selected high')).priority == 'high'
    signin('other')
    assert b'WiFi lantai dua' not in client.get('/').data
    assert b'Selected high' not in client.get('/').data


def test_activity_labels_are_indonesian(app, client, signin, ticket):
    signin('admin')
    assert client.post(f'/tickets/{ticket}/update', data={'status': 'in_progress', 'priority': 'high'}).status_code == 302
    soup = BeautifulSoup(client.get(f'/tickets/{ticket}').data, 'html.parser')
    history = soup.select_one('ol').get_text()
    assert 'Terbuka → Diproses' in history
    assert 'Normal → Tinggi' in history
    assert 'in_progress' not in history


def test_create_admin_cli_and_time(app):
    runner=app.test_cli_runner()
    args=['create-admin','--email','cli@example.test','--name','CLI Admin','--password','a-long-cli-password']
    assert runner.invoke(args=args).exit_code==0
    assert runner.invoke(args=args).exit_code!=0
    from datetime import datetime
    with app.app_context():
        assert app.jinja_env.filters['jakarta'](datetime(2026,1,1,0,0)).endswith('07:00 WIB')


def test_xss_escaped_and_no_events_on_rejected_update(app,client,signin,ticket):
    client.post(f'/tickets/{ticket}/reply',data={'body':'<script>alert(1)</script>'})
    response=client.get(f'/tickets/{ticket}')
    assert b'<script>alert(1)</script>' not in response.data
    assert b'&lt;script&gt;' in response.data
    signin('admin')
    with app.app_context():
        before=db.session.scalar(db.select(db.func.count()).select_from(TicketEvent))
    assert client.post(f'/tickets/{ticket}/update',data={'status':'closed','priority':'high'}).status_code==409
    with app.app_context():
        t=db.session.get(Ticket,ticket)
        assert t.status=='open' and t.priority=='normal'
        assert db.session.scalar(db.select(db.func.count()).select_from(TicketEvent))==before
