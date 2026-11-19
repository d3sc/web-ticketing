import pytest
from helpdesk import db
from helpdesk.models import User

OLD = 'Test-password-123'
NEW = 'Password-baru-2026!'


def user_id(app, name):
    with app.app_context():
        return db.session.scalar(db.select(User.id).where(User.name == name))


def payload(**changes):
    return dict(current_password=OLD, password=NEW, confirm_password=NEW, **changes)


@pytest.mark.parametrize('target', ['employee', 'agent', 'admin'])
def test_admin_changes_password(app, client, signin, target):
    uid = user_id(app, target)
    signin('admin')
    response = client.get(f'/admin/users/{uid}/password')
    assert response.status_code == 200
    assert b'Ganti Password' in response.data
    response = client.post(f'/admin/users/{uid}/password', data=payload(), follow_redirects=True)
    assert response.status_code == 200
    assert 'Password berhasil diubah.' in response.text
    with app.app_context():
        user = db.session.get(User, uid)
        assert user.check_password(NEW)
        assert not user.check_password(OLD)
        assert user.password_hash != NEW
    client.post('/logout')
    assert client.post('/login', data={'email': f'{target}@example.test', 'password': OLD}).status_code == 400
    assert client.post('/login', data={'email': f'{target}@example.test', 'password': NEW}).status_code == 302


@pytest.mark.parametrize('actor', ['employee', 'agent'])
def test_non_admin_cannot_change_password(app, client, signin, actor):
    uid = user_id(app, 'employee')
    signin(actor)
    assert client.get(f'/admin/users/{uid}/password').status_code == 403
    assert client.post(f'/admin/users/{uid}/password', data=payload()).status_code == 403
    with app.app_context():
        assert db.session.get(User, uid).check_password(OLD)


@pytest.mark.parametrize('change,message', [
    ({'current_password': 'Wrong-password-123'}, 'Password administrator saat ini tidak sesuai.'),
    ({'password': 'short', 'confirm_password': 'short'}, 'Password harus terdiri dari 12–128 karakter.'),
    ({'password': 'a' * 129, 'confirm_password': 'a' * 129}, 'Password harus terdiri dari 12–128 karakter.'),
    ({'confirm_password': 'Tidak-sama-2026'}, 'Konfirmasi password tidak sama.'),
    ({'password': '', 'confirm_password': ''}, 'Kolom ini wajib diisi.'),
])
def test_invalid_password_change_does_not_mutate(app, client, signin, change, message):
    uid = user_id(app, 'employee')
    signin('admin')
    data = payload()
    data.update(change)
    response = client.post(f'/admin/users/{uid}/password', data=data)
    assert response.status_code == 400
    assert message in response.text
    assert NEW not in response.text
    assert OLD not in response.text
    with app.app_context():
        assert db.session.get(User, uid).check_password(OLD)


def test_password_change_csrf(app, client, signin):
    uid = user_id(app, 'employee')
    signin('admin')
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post(f'/admin/users/{uid}/password', data=payload()).status_code == 400
    with app.app_context():
        assert db.session.get(User, uid).check_password(OLD)


def test_password_change_unknown_and_anonymous(app, client, signin):
    assert client.get('/admin/users/999999/password').status_code == 302
    assert client.post('/admin/users/999999/password', data=payload()).status_code == 302
    signin('admin')
    assert client.get('/admin/users/999999/password').status_code == 404
    assert client.post('/admin/users/999999/password', data=payload()).status_code == 404


def test_users_list_has_password_action(app, client, signin):
    signin('admin')
    response = client.get('/admin/users')
    for name in ['employee', 'agent', 'admin']:
        assert f'/admin/users/{user_id(app, name)}/password' in response.text
