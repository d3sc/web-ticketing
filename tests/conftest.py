import os
import pytest
from sqlalchemy.engine import make_url
from helpdesk import create_app, db

@pytest.fixture()
def app():
    url = os.environ.get('TEST_DATABASE_URL', '')
    assert make_url(url).database == 'helpdesk_test', 'Tests require isolated helpdesk_test schema'
    app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': url, 'SECRET_KEY': 'test-secret', 'WTF_CSRF_ENABLED': False})
    with app.app_context():
        from helpdesk.models import User, Category
        # Delete test data only; schema is installed by real Alembic migrations.
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        for name, role in [('employee','employee'), ('other','employee'), ('agent','it'), ('agent2','it'), ('admin','admin')]:
            user = User(name=name, email=f'{name}@example.test', role=role)
            user.set_password('Test-password-123')
            db.session.add(user)
        db.session.add(Category(code='Network', name='Jaringan'))
        db.session.commit()
    yield app

@pytest.fixture()
def client(app):
    return app.test_client()

@pytest.fixture()
def signin(client):
    def sign(name):
        client.post('/logout')
        return client.post('/login', data={'email': f'{name}@example.test', 'password': 'Test-password-123'})
    return sign

@pytest.fixture()
def ticket(app, client, signin):
    from helpdesk.models import Ticket, Category
    signin('employee')
    with app.app_context():
        cid = db.session.scalar(db.select(Category.id))
    response = client.post('/tickets/new', data={'title':'WiFi lantai dua', 'description':'Tidak dapat terhubung ke jaringan kantor.', 'category_id': cid})
    assert response.status_code == 302
    with app.app_context():
        return db.session.scalar(db.select(Ticket.id))
