import pytest
from helpdesk import db
from helpdesk.models import User, Category, Ticket


@pytest.mark.parametrize('role', ['employee', 'agent'])
def test_settings_admin_only(app, client, signin, role):
    signin(role)
    for path in ['/admin/settings/telegram', '/admin/settings/telegram/test']:
        if not path.endswith('/test'):
            assert client.get(path).status_code == 403
        assert client.post(path, data={'enabled': 'y', 'chat_id': '-1001234'}).status_code == 403


def test_admin_save_negative_id_and_toggle(app, client, signin):
    signin('admin')
    assert client.get('/admin/settings/telegram').status_code == 200
    response = client.post('/admin/settings/telegram', data={'enabled': 'y', 'chat_id': '-10012345678'}, follow_redirects=True)
    assert response.status_code == 200
    assert 'Pengaturan Telegram berhasil disimpan.' in response.text
    from helpdesk.models import TelegramSettings
    with app.app_context():
        settings = db.session.get(TelegramSettings, 1)
        assert settings.enabled and settings.chat_id == '-10012345678'
    assert client.post('/admin/settings/telegram', data={'chat_id': '-10012345678'}).status_code == 302
    with app.app_context():
        assert not db.session.get(TelegramSettings, 1).enabled


@pytest.mark.parametrize('chat', ['', 'abc', '0', '+123', '@someone', '1' * 33, '12.3', '-1x'])
def test_invalid_destination_rejected(app, client, signin, chat):
    signin('admin')
    response = client.post('/admin/settings/telegram', data={'enabled': 'y', 'chat_id': chat})
    assert response.status_code == 400
    assert 'Chat ID harus berupa angka positif atau negatif, bukan nol (maksimal 32 karakter).' in response.text


def test_settings_and_test_csrf(app, client, signin):
    signin('admin')
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post('/admin/settings/telegram', data={'enabled': 'y', 'chat_id': '123'}).status_code == 400
    assert client.post('/admin/settings/telegram/test').status_code == 400


def test_test_uses_saved_destination_and_safe_errors(app, client, signin, monkeypatch):
    from helpdesk import telegram as tg
    signin('admin')
    client.post('/admin/settings/telegram', data={'chat_id': '-1234'})
    calls = []
    monkeypatch.setattr(tg, 'send_message', lambda *args: calls.append(args) or 88)
    response = client.post('/admin/settings/telegram/test', data={'chat_id': '-9999'}, follow_redirects=True)
    assert response.status_code == 200
    assert calls[0][0] == '-1234'
    assert 'Pesan tes berhasil dikirim' in response.text
    def fail(*args):
        raise tg.TelegramDeliveryError('Bot tidak diizinkan mengirim pesan; tambahkan bot dan periksa izin chat.')
    monkeypatch.setattr(tg, 'send_message', fail)
    response = client.post('/admin/settings/telegram/test', follow_redirects=True)
    assert 'tambahkan bot dan periksa izin chat' in response.text
    app.config['TELEGRAM_BOT_TOKEN'] = 'never-show-this-token'
    assert 'never-show-this-token' not in client.get('/admin/settings/telegram').text


def test_missing_destination_test_error(app, client, signin):
    signin('admin')
    response = client.post('/admin/settings/telegram/test', follow_redirects=True)
    assert 'Simpan Chat ID Tujuan yang valid terlebih dahulu.' in response.text


def test_new_ticket_only_committed_outbox_and_delivery_failure(app, client, signin, monkeypatch):
    from helpdesk import telegram as tg
    from helpdesk.models import TelegramOutbox
    app.config.update(APP_BASE_URL='http://100.100.100.10:5017', TELEGRAM_BOT_TOKEN='mock-token')
    signin('admin')
    assert client.post('/admin/settings/telegram', data={'enabled': 'y', 'chat_id': '-100123'}).status_code == 302
    signin('employee')
    calls = []
    def transport(*args):
        calls.append(args)
        return {'ok': False, 'error_code': 503}
    monkeypatch.setattr(tg, '_transport', transport)
    with app.app_context():
        cid = db.session.scalar(db.select(Category.id))
    response = client.post('/tickets/new', data={'title': 'Telegram test', 'description': 'Tidak bocor ke notifikasi', 'priority': 'high', 'category_id': cid})
    assert response.status_code == 302
    assert not calls, 'Ticket creation must not perform HTTP'
    tid = int(response.location.rsplit('/', 1)[1])
    with app.app_context():
        row = db.session.scalar(db.select(TelegramOutbox))
        assert row.ticket_id == tid and row.state == 'pending'
        assert row.url == f'http://100.100.100.10:5017/tickets/{tid}'
        assert 'Tinggi' in row.text and 'WIB' in row.text
        db.session.remove()
        assert tg.process_outbox() == 1
        db.session.remove()
        assert db.session.get(Ticket, tid) is not None
        row = db.session.scalar(db.select(TelegramOutbox))
        assert row.state == 'pending' and row.attempts == 1 and row.last_error
    assert client.post(f'/tickets/{tid}/reply', data={'body': 'Balasan karyawan'}).status_code == 302
    signin('admin')
    with app.app_context():
        aid = db.session.scalar(db.select(User.id).where(User.name == 'agent'))
    assert client.post(f'/tickets/{tid}/assign', data={'assignee_id': aid}).status_code == 302
    assert client.post(f'/tickets/{tid}/update', data={'status': 'in_progress', 'priority': 'low'}).status_code == 302
    assert client.post(f'/tickets/{tid}/reply', data={'body': 'Balasan admin'}).status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(TelegramOutbox)) == 1
    assert len(calls) == 1


def test_disabled_no_notification(app, client, signin):
    from helpdesk.models import TelegramOutbox
    signin('employee')
    with app.app_context():
        cid = db.session.scalar(db.select(Category.id))
    assert client.post('/tickets/new', data={'title': 'Tanpa notifikasi', 'description': 'Uji', 'category_id': cid}).status_code == 302
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(TelegramOutbox)) == 0
