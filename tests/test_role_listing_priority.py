from contextlib import contextmanager
from urllib.parse import urlsplit, parse_qs

import pytest
from flask import template_rendered
from helpdesk import db
from helpdesk.models import Ticket, User, Category


@contextmanager
def rendered(app):
    contexts = []
    def capture(sender, template, context, **extra):
        from copy import copy
        from types import SimpleNamespace
        context = dict(context)
        if 'pagination' in context:
            pagination = copy(context['pagination'])
            pagination.items = [SimpleNamespace(id=t.id, creator_id=t.creator_id) for t in pagination.items]
            context['pagination'] = pagination
        contexts.append((template.name, context))
    template_rendered.connect(capture, app)
    try:
        yield contexts
    finally:
        template_rendered.disconnect(capture, app)


@pytest.mark.parametrize('name,path', [('employee','/'), ('agent','/tickets'), ('admin','/tickets')])
def test_role_destinations(client, signin, name, path):
    assert urlsplit(signin(name).location).path == path
    response = client.get('/')
    if name == 'employee':
        assert response.status_code == 200
    else:
        assert response.status_code == 302
        assert urlsplit(response.location).path == '/tickets'
    assert client.get('/tickets').status_code == (403 if name == 'employee' else 200)


def test_owner_scoped_listing_counts_filters_and_pages(app, client, signin):
    with app.app_context():
        users = {u.name: u.id for u in db.session.scalars(db.select(User))}
        cid = db.session.scalar(db.select(Category.id))
        for owner in ('employee', 'other'):
            for i in range(25):
                db.session.add(Ticket(title=f'{owner} needle {i}', description='Test', creator_id=users[owner], category_id=cid, status='open' if i < 22 else 'closed', priority='high' if i == 0 else 'normal'))
        db.session.commit()
        own_id = db.session.scalar(db.select(Ticket.id).where(Ticket.creator_id == users['employee'], Ticket.priority == 'high'))
    for name in ('employee', 'other', 'agent'):
        signin(name)
        path = '/tickets' if name == 'agent' else '/'
        with rendered(app) as contexts:
            assert client.get(path).status_code == 200
        template, ctx = contexts[-1]
        assert template == 'queue.html'
        assert ctx['is_employee'] == (name != 'agent')
        assert ctx['list_endpoint'] == ('tickets.queue' if name == 'agent' else 'tickets.dashboard')
        assert ctx['counts'] == {'open': 44 if name == 'agent' else 22, 'closed': 6 if name == 'agent' else 3}
        assert ctx['total_tickets'] == (50 if name == 'agent' else 25)
        assert len(ctx['pagination'].items) == 20
        assert not ctx['has_filters']
        assert bool(ctx['agents']) == (name == 'agent')
        if name != 'agent':
            assert all(t.creator_id == users[name] for t in ctx['pagination'].items)
        with rendered(app) as contexts:
            assert client.get(path + '?status=open&q=needle&page=2').status_code == 200
        ctx = contexts[-1][1]
        assert ctx['counts']['closed'] == (6 if name == 'agent' else 3)
        assert len(ctx['pagination'].items) == (20 if name == 'agent' else 2)
        assert ctx['has_filters']
        with app.test_request_context(path):
            link = urlsplit(ctx['pagination_url'](1))
        assert link.path == path
        assert parse_qs(link.query) == {'status':['open'], 'q':['needle'], 'page':['1']}
    signin('employee')
    with rendered(app) as contexts:
        assert client.get(f'/?q=IT-{own_id:06d}&priority=high&category_id={cid}').status_code == 200
    assert [t.id for t in contexts[-1][1]['pagination'].items] == [own_id]
    for query in ('q=other', 'status=closed&priority=high', 'page=999', 'q=%25'):
        with rendered(app) as contexts:
            assert client.get('/?' + query).status_code == 200
        assert not contexts[-1][1]['pagination'].items
    for query in ('category_id=bad', 'status=bogus', 'priority=bogus', 'assignee_id=bad'):
        assert client.get('/?' + query).status_code == 400


def test_employee_denials_leave_ticket_untouched(app, client, signin, ticket):
    signin('other')
    for suffix, data in (('', None), ('/reply', {'body':'Forbidden'}), ('/update', {'status':'in_progress'}), ('/claim', {}), ('/assign', {'assignee_id':1})):
        response = client.get(f'/tickets/{ticket}') if data is None else client.post(f'/tickets/{ticket}{suffix}', data=data)
        assert response.status_code == 403
    for path in ('/admin/users', '/admin/categories', '/admin/users/1', '/admin/categories/1'):
        assert client.post(path, data={}).status_code == 403
    for path in ('/admin/users', '/admin/categories'):
        assert client.get(path).status_code == 403
    with app.app_context():
        t = db.session.get(Ticket, ticket)
        assert t.status == 'open' and t.assignee_id is None
        assert len(t.events) == 1 and not t.comments


@pytest.mark.parametrize('priority', ['low', 'normal', 'high', None])
def test_create_priority_saved(app, client, signin, priority):
    signin('employee')
    with app.app_context():
        cid = db.session.scalar(db.select(Category.id))
    data = {'title':'Priority ticket', 'description':'Test', 'category_id':cid}
    if priority is not None:
        data['priority'] = priority
    response = client.post('/tickets/new', data=data)
    assert response.status_code == 302
    with app.app_context():
        t = db.session.scalar(db.select(Ticket))
        assert t.priority == (priority or 'normal')
        tid = t.id
    label = {'low':'Rendah', 'normal':'Normal', 'high':'Tinggi'}[priority or 'normal']
    assert label.encode() in client.get(f'/tickets/{tid}').data
    from bs4 import BeautifulSoup
    for role, path in [('employee', '/'), ('agent', '/tickets'), ('admin', '/tickets')]:
        signin(role)
        soup = BeautifulSoup(client.get(path).data, 'html.parser')
        row = soup.select_one('tbody tr')
        assert row and label in row.get_text()
        assert f'IT-{tid:06d}' in row.get_text()


@pytest.mark.parametrize('priority', ['', 'urgent', 'HIGH', 'normal<script>'])
def test_invalid_priority_no_ticket(app, client, signin, priority):
    signin('employee')
    with app.app_context():
        cid = db.session.scalar(db.select(Category.id))
    with rendered(app) as contexts:
        response = client.post('/tickets/new', data={'title':'No row', 'description':'Test', 'category_id':cid, 'priority':priority})
    assert response.status_code == 400
    assert 'Prioritas tidak valid.' in contexts[-1][1]['form'].priority.errors
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(Ticket)) == 0


def test_priority_choices_default_and_preserved(app, client, signin):
    signin('employee')
    with rendered(app) as contexts:
        assert client.get('/tickets/new').status_code == 200
    field = contexts[-1][1]['form'].priority
    assert field.choices == [('low','Rendah'), ('normal','Normal'), ('high','Tinggi')]
    assert field.data == 'normal'
    with rendered(app) as contexts:
        assert client.post('/tickets/new', data={'priority':'high'}).status_code == 400
    assert contexts[-1][1]['form'].priority.data == 'high'
