from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from bs4 import BeautifulSoup
from helpdesk import db


def test_models_and_defaults(app, ticket):
    from helpdesk.models import Ticket
    with app.app_context():
        t = db.session.get(Ticket, ticket)
        assert t.reference == f'IT-{ticket:06d}'
        assert (t.status, t.priority, t.assignee_id) == ('open', 'normal', None)
        assert t.created_at is not None


def test_workflow_and_events(app, client, signin, ticket):
    from helpdesk.models import Ticket, TicketEvent
    signin('agent')
    assert client.post(f'/tickets/{ticket}/claim').status_code == 302
    for status in ['in_progress', 'resolved', 'in_progress', 'resolved', 'closed']:
        assert client.post(f'/tickets/{ticket}/update', data={'status':status, 'priority':'high'}).status_code == 302
    with app.app_context():
        assert db.session.get(Ticket,ticket).status == 'closed'
        events = db.session.scalars(db.select(TicketEvent).where(TicketEvent.ticket_id==ticket)).all()
        assert len(events) == 7
        assert all(e.actor_id and e.created_at for e in events)
    assert client.post(f'/tickets/{ticket}/reply', data={'body':'Terlambat'}).status_code == 409


def test_direct_url_authorization(client, signin, ticket):
    signin('other')
    assert client.get(f'/tickets/{ticket}').status_code == 403
    assert client.post(f'/tickets/{ticket}/reply', data={'body':'Tidak sah'}).status_code == 403
    assert client.post(f'/tickets/{ticket}/update', data={'status':'in_progress'}).status_code == 403
    assert client.get('/admin/users').status_code == 403
    signin('agent')
    assert client.post(f'/tickets/{ticket}/reply', data={'body':'Belum ditugaskan'}).status_code == 403
    assert client.post(f'/tickets/{ticket}/update', data={'status':'in_progress'}).status_code == 403
    client.post(f'/tickets/{ticket}/claim')
    signin('agent2')
    assert client.post(f'/tickets/{ticket}/claim').status_code == 409
    assert client.post(f'/tickets/{ticket}/reply',data={'body':'Bukan tiket saya'}).status_code == 403


def test_invalid_transitions_and_employee_reply(client, signin, ticket):
    assert client.post(f'/tickets/{ticket}/reply',data={'body':'Informasi tambahan'}).status_code == 302
    assert client.post(f'/tickets/{ticket}/claim').status_code == 403
    signin('admin')
    for status in ['closed','resolved','garbage']:
        assert client.post(f'/tickets/{ticket}/update', data={'status':status}).status_code in (400,409)
    for status in ['in_progress','resolved']:
        assert client.post(f'/tickets/{ticket}/update',data={'status':status}).status_code == 302
    signin('employee')
    assert client.post(f'/tickets/{ticket}/reply',data={'body':'Terima kasih'}).status_code == 302
    signin('admin')
    client.post(f'/tickets/{ticket}/update',data={'status':'closed'})
    assert client.post(f'/tickets/{ticket}/update',data={'status':'in_progress'}).status_code == 409


def test_admin_assignment_and_accounts(app, client, signin, ticket):
    from helpdesk.models import User, Ticket
    signin('admin')
    with app.app_context():
        agent = db.session.scalar(db.select(User).where(User.role=='it'))
        aid = agent.id
        eid = db.session.scalar(db.select(User.id).where(User.role=='employee'))
    assert client.post(f'/tickets/{ticket}/assign',data={'assignee_id':eid}).status_code == 400
    assert client.post(f'/tickets/{ticket}/assign',data={'assignee_id':aid}).status_code == 302
    assert client.post('/admin/users',data={'name':'Baru','email':'new@example.test','password':'Strong-Password-123','role':'employee'}).status_code == 302
    assert client.post('/admin/users',data={'name':'Bad','email':'bad','password':'x','role':'root'}).status_code == 400
    assert client.post(f'/admin/users/{aid}',data={'role':'it','active':'0'}).status_code == 409  # must reassign active work first
    with app.app_context():
        uid = db.session.scalar(db.select(User.id).where(User.email=='new@example.test'))
    assert client.post(f'/admin/users/{uid}',data={'role':'it','active':'1'}).status_code == 302
    assert client.post(f'/tickets/{ticket}/assign',data={'assignee_id':uid}).status_code == 302
    assert client.post(f'/admin/users/{aid}',data={'role':'it','active':'0'}).status_code == 302
    assert client.post(f'/tickets/{ticket}/assign',data={'assignee_id':aid}).status_code == 400
    signin('agent')
    assert client.get('/').status_code == 302


def test_categories_and_validation(app, client, signin):
    from helpdesk.models import Category
    signin('admin')
    assert client.post('/admin/categories',data={'code':'Hardware','name':'Perangkat Keras'}).status_code == 302
    assert client.post('/admin/categories',data={'code':'Hardware','name':'Duplikat'}).status_code == 400
    assert client.post('/admin/categories',data={'code':'','name':''}).status_code == 400
    with app.app_context():
        cid = db.session.scalar(db.select(Category.id).where(Category.code=='Hardware'))
    assert client.post(f'/admin/categories/{cid}',data={'name':'Perangkat','active':'0'}).status_code == 302
    signin('employee')
    for data in [{}, {'title':'Title','description':'desc','category_id':99999}, {'title':'Title','description':'desc','category_id':cid}]:
        assert client.post('/tickets/new',data=data).status_code == 400


def test_auth_csrf_inactive_session(app, client, signin):
    from helpdesk.models import User
    assert client.get('/').status_code == 302
    assert client.post('/login',data={'email':'employee@example.test','password':'wrong'}).status_code == 400
    signin('employee')
    with app.app_context():
        u = db.session.scalar(db.select(User).where(User.name=='employee'))
        u.active=False
        db.session.commit()
    assert client.get('/').status_code == 302
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post('/login',data={'email':'admin@example.test','password':'Test-password-123'}).status_code == 400
    html = client.get('/login').data
    token = BeautifulSoup(html,'html.parser').select_one('input[name=csrf_token]')['value']
    assert client.post('/login',data={'csrf_token':token,'email':'admin@example.test','password':'Test-password-123'}).status_code == 302
    assert client.post('/admin/categories',data={'name':'No token','code':'Bad'}).status_code == 400


def test_dashboard_queue_search_and_pagination(app, client, signin, ticket):
    signin('employee')
    assert b'Tiket Saya' in client.get('/').data
    assert b'WiFi lantai dua' in client.get('/').data
    assert b'WiFi lantai dua' not in client.get('/?q=missing').data
    assert client.get('/tickets').status_code == 403
    signin('agent')
    assert b'WiFi lantai dua' in client.get('/tickets?status=open&priority=normal').data
    assert b'WiFi lantai dua' not in client.get('/tickets?status=closed').data
    assert client.get('/tickets?page=bad').status_code == 200
    assert client.get('/tickets?page=999').status_code == 200


def test_seed_categories_idempotent(app):
    from helpdesk.models import Category
    runner=app.test_cli_runner()
    assert runner.invoke(args=['seed-categories']).exit_code == 0
    assert runner.invoke(args=['seed-categories']).exit_code == 0
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Category)) == 4
        assert set(db.session.scalars(db.select(Category.code))) == {'Network', 'Hardware', 'Accounts and Access', 'Applications'}


def test_two_simultaneous_claims_exactly_one_winner(app, ticket):
    from helpdesk.models import User, Ticket, TicketEvent
    barrier=Barrier(2)
    def claim(name):
        with app.test_client() as c:
            c.post('/login',data={'email':name+'@example.test','password':'Test-password-123'})
            barrier.wait(timeout=10)
            return c.post(f'/tickets/{ticket}/claim').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(claim,n) for n in ['agent','agent2']]
        results=[f.result(timeout=20) for f in futures]
    assert sorted(results)==[302,409]
    with app.app_context():
        assert db.session.get(Ticket,ticket).assignee_id is not None
        assert db.session.scalar(db.select(db.func.count()).select_from(TicketEvent).where(TicketEvent.ticket_id==ticket,TicketEvent.kind=='assignment'))==1
