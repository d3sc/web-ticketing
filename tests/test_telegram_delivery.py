"""Isolated migrated MySQL/SQLite tests; no real Telegram requests or live database."""
import io
import json
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError

import pytest
from flask_migrate import upgrade
from sqlalchemy.exc import IntegrityError, DBAPIError

from helpdesk import create_app, db
from helpdesk.models import Category, Ticket, User, TelegramSettings, TelegramOutbox
from helpdesk import telegram as tg


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(tg, '_transport', lambda *a: pytest.fail('Unmocked Telegram transport'))


@pytest.fixture()
def app(tmp_path):
    from sqlalchemy.engine import make_url
    url = os.environ.get('TEST_DATABASE_URL') or f'sqlite:///{tmp_path}/helpdesk_test'
    assert make_url(url).database == 'helpdesk_test' or make_url(url).database == str(tmp_path / 'helpdesk_test')
    app = create_app({'TESTING': True, 'SECRET_KEY': 'test',
                      'SQLALCHEMY_DATABASE_URI': url,
                      'APP_BASE_URL': 'https://desk.example.test',
                      'TELEGRAM_BOT_TOKEN': 'secret-token'})
    with app.app_context():
        upgrade(directory='migrations')
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.add(TelegramSettings(id=1, enabled=False, chat_id=''))
        db.session.commit()
        yield app
        db.session.remove()
        db.engine.dispose()


@pytest.fixture()
def ticket(app):
    user = User(name='Test', email='test@example.test', password_hash='unused')
    category = Category(code='network', name='Jaringan')
    ticket = Ticket(title='<b>WiFi & kantor</b>', description='private description',
                    creator=user, category=category, priority='high',
                    created_at=datetime(2026, 1, 2, 0, 15))
    db.session.add_all([user, category, ticket])
    db.session.flush()
    return ticket


def enable():
    settings = db.session.get(TelegramSettings, 1)
    if settings is None:
        settings = TelegramSettings(id=1)
        db.session.add(settings)
    settings.enabled = True
    settings.chat_id = '-100123456789'
    db.session.flush()
    return settings


def enqueue(ticket):
    enable()
    row = tg.queue_new_ticket(ticket)
    db.session.commit()
    return row


def test_queue_snapshot_plain_text_and_transaction(app, ticket, monkeypatch):
    monkeypatch.setattr(tg, '_transport', lambda *a: pytest.fail('HTTP during enqueue'))
    assert tg.queue_new_ticket(ticket) is None
    settings = enable()
    row = tg.queue_new_ticket(ticket)
    assert row.ticket_id == ticket.id
    assert row.chat_id == settings.chat_id
    assert row.url == f'https://desk.example.test/tickets/{ticket.id}'
    assert all(part in row.text for part in ['Tiket baru masuk', ticket.reference,
               ticket.title, 'Jaringan', 'Tinggi', '02/01/2026 07:15 WIB'])
    assert 'private description' not in row.text
    assert row.url in row.text
    db.session.flush()
    assert row.state == 'pending' and row.attempts == 0
    db.session.rollback()
    assert db.session.scalar(db.select(db.func.count()).select_from(TelegramOutbox)) == 0


@pytest.mark.parametrize('chat', ['', 'abc', '@channel', '123 45', '1' * 33, '0'])
def test_invalid_chat_skips(app, ticket, chat):
    enable().chat_id = chat
    assert tg.queue_new_ticket(ticket) is None


@pytest.mark.parametrize('base', ['', 'localhost', 'ftp://desk.test', 'http://localhost',
    'https://user:pass@desk.test', 'https://desk.test?q=1', 'https://desk.test/#x'])
def test_bad_base_never_breaks_creation_and_fails_safely(app, ticket, base, monkeypatch):
    app.config['APP_BASE_URL'] = base
    row = enqueue(ticket)
    assert row.url == ''
    monkeypatch.setattr(tg, '_transport', lambda *a: pytest.fail('invalid configuration sent'))
    assert tg.process_outbox() == 1
    db.session.rollback()
    assert row.state == 'failed' and row.attempts == 1
    assert 'APP_BASE_URL' in row.last_error


def test_private_vpn_base_and_unique_ticket(app, ticket):
    app.config['APP_BASE_URL'] = 'http://10.2.3.4:8080/helpdesk/'
    row = enqueue(ticket)
    assert row.url == f'http://10.2.3.4:8080/helpdesk/tickets/{ticket.id}'
    db.session.add(TelegramOutbox(ticket_id=ticket.id, chat_id='123', text='x', url=''))
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_send_payload_and_keyboard_fallback(app, monkeypatch):
    payloads = []
    def transport(token, payload):
        assert token == 'secret-token'
        payloads.append(payload)
        if len(payloads) == 1:
            raise HTTPError('redacted', 400, '', {}, io.BytesIO(json.dumps(
                {'ok': False, 'description': 'Bad Request: inline keyboard button URL is invalid'}).encode()))
        return {'ok': True, 'result': {'message_id': 42}}
    monkeypatch.setattr(tg, '_transport', transport)
    assert tg.send_message('-123', '<b>plain</b>', 'https://desk.test/tickets/1') == 42
    assert 'parse_mode' not in payloads[0]
    assert payloads[0]['reply_markup']['inline_keyboard'][0][0]['text'] == 'Buka Tiket'
    assert 'reply_markup' not in payloads[1]
    assert 'https://desk.test/tickets/1' in payloads[1]['text']


@pytest.mark.parametrize('code,transient', [(400, False), (401, False), (403, False), (429, True), (500, True), (503, True)])
def test_safe_http_errors(app, monkeypatch, code, transient):
    calls = []
    def transport(*args):
        calls.append(1)
        raise HTTPError('https://secret-token', code, 'secret-token', {}, io.BytesIO(json.dumps(
            {'description': 'secret-token unrelated bad request', 'parameters': {'retry_after': 90}}).encode()))
    monkeypatch.setattr(tg, '_transport', transport)
    with pytest.raises(tg.TelegramDeliveryError) as exc:
        tg.send_message('123', 'hello', 'https://desk.test')
    assert exc.value.transient is transient
    assert 'secret-token' not in str(exc.value)
    assert len(calls) == 1
    if code == 429:
        assert exc.value.retry_after == 90


@pytest.mark.parametrize('result', [None, [], {}, {'ok': True}, {'ok': True, 'result': {}},
                                      {'ok': False, 'error_code': 401, 'description': 'secret-token'}])
def test_malformed_or_unsuccessful_response(app, monkeypatch, result):
    monkeypatch.setattr(tg, '_transport', lambda *a: result)
    with pytest.raises(tg.TelegramDeliveryError) as exc:
        tg.send_message('123', 'hello')
    assert 'secret-token' not in str(exc.value)


@pytest.mark.parametrize('error', [TimeoutError('secret-token'), URLError('secret-token'), ValueError('secret-token')])
def test_network_and_json_errors(app, monkeypatch, error):
    def transport(*a):
        raise error
    monkeypatch.setattr(tg, '_transport', transport)
    with pytest.raises(tg.TelegramDeliveryError) as exc:
        tg.send_message('123', 'hello')
    assert exc.value.transient
    assert 'secret-token' not in str(exc.value)


def test_missing_token_is_permanent(app):
    app.config['TELEGRAM_BOT_TOKEN'] = ''
    with pytest.raises(tg.TelegramDeliveryError) as exc:
        tg.send_message('123', 'hello')
    assert not exc.value.transient


def test_worker_success_pause_snapshot_no_resend(app, ticket, monkeypatch):
    row = enqueue(ticket)
    settings = db.session.get(TelegramSettings, 1)
    settings.enabled = False
    db.session.commit()
    calls = []
    monkeypatch.setattr(tg, 'send_message', lambda *a: calls.append(a) or 42)
    assert tg.process_outbox() == 0
    db.session.rollback()
    settings.enabled = True
    settings.chat_id = '-999'
    db.session.commit()
    assert tg.process_outbox(limit=1) == 1
    db.session.rollback()
    assert row.state == 'sent' and row.sent_at and row.attempts == 1
    assert calls[0][0] == '-100123456789'
    assert tg.process_outbox() == 0
    db.session.rollback()


def test_worker_retry_after_backoff_and_terminal_limit(app, ticket, monkeypatch):
    row = enqueue(ticket)
    def fail(*a):
        raise tg.TelegramDeliveryError('Terlalu banyak permintaan.', transient=True, retry_after=90)
    monkeypatch.setattr(tg, 'send_message', fail)
    before = datetime.utcnow()
    assert tg.process_outbox() == 1
    db.session.rollback()
    assert row.state == 'pending' and row.attempts == 1
    assert row.available_at >= before + timedelta(seconds=90)
    assert tg.process_outbox() == 0
    db.session.rollback()
    row.attempts = 7
    row.available_at = before - timedelta(seconds=1)
    db.session.commit()
    assert tg.process_outbox() == 1
    db.session.rollback()
    assert row.state == 'failed' and row.attempts == 8
    assert tg.process_outbox() == 0
    db.session.rollback()


def test_permanent_failure_and_cli_limit(app, ticket, monkeypatch):
    row = enqueue(ticket)
    def fail(*a):
        raise tg.TelegramDeliveryError('Bot tidak diizinkan mengirim pesan.', transient=False)
    monkeypatch.setattr(tg, 'send_message', fail)
    tg.register_cli(app)
    runner = app.test_cli_runner()
    assert runner.invoke(args=['telegram-worker', '--once', '--limit', '0']).exit_code == 2
    assert runner.invoke(args=['telegram-worker', '--once', '--limit', '101']).exit_code == 2
    result = runner.invoke(args=['telegram-worker', '--once'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['processed'] == 1
    db.session.rollback()
    assert row.state == 'failed'


def test_uncommitted_outbox_is_invisible_to_worker(app, ticket, monkeypatch):
    enable()
    db.session.commit()
    tg.queue_new_ticket(ticket)
    db.session.flush()
    monkeypatch.setattr(tg, 'send_message', lambda *a: pytest.fail('Uncommitted row sent'))
    assert tg.process_outbox() == 0
    db.session.rollback()
    assert db.session.get(Ticket, ticket.id) is not None
    assert db.session.scalar(db.select(TelegramOutbox)) is None


def test_exponential_backoff_without_retry_after(app, ticket, monkeypatch):
    row = enqueue(ticket)
    def fail(*a):
        raise tg.TelegramDeliveryError('Koneksi Telegram bermasalah.', transient=True)
    monkeypatch.setattr(tg, 'send_message', fail)
    row.attempts = 2
    db.session.commit()
    before = datetime.utcnow()
    assert tg.process_outbox() == 1
    db.session.rollback()
    assert row.attempts == 3 and row.state == 'pending'
    assert row.available_at >= before + timedelta(seconds=20)


def test_migration_seed_constraints_and_mysql_lock_sql(app):
    from sqlalchemy.dialects import mysql
    settings = db.session.get(TelegramSettings, 1)
    assert settings.enabled is False and settings.chat_id == ''
    db.session.add(TelegramSettings(id=2))
    with pytest.raises(DBAPIError) as exc:
        db.session.flush()
    assert 'telegram_settings_singleton' in str(exc.value)
    db.session.rollback()
    sql = str(db.select(TelegramOutbox).limit(1).with_for_update(skip_locked=True)
              .compile(dialect=mysql.dialect()))
    assert 'FOR UPDATE SKIP LOCKED' in sql


def test_migration_downgrade_and_reupgrade(app):
    from flask_migrate import downgrade
    from sqlalchemy import inspect
    db.session.remove()
    downgrade(directory='migrations', revision='0001_initial')
    assert 'telegram_outbox' not in inspect(db.engine).get_table_names()
    assert 'tickets' in inspect(db.engine).get_table_names()
    upgrade(directory='migrations')
    assert db.session.get(TelegramSettings, 1).enabled is False
