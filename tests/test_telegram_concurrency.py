"""MySQL-only concurrency check for the transactional Telegram outbox."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from helpdesk import db
from helpdesk.models import Category, TelegramSettings, TelegramOutbox
from helpdesk import telegram as tg


def test_two_workers_send_one_committed_message(app, client, signin, monkeypatch):
    with app.app_context():
        if db.engine.dialect.name != 'mysql':
            pytest.skip('Requires MySQL SKIP LOCKED')
        db.session.add(TelegramSettings(id=1, enabled=True, chat_id='-100123'))
        db.session.commit()
        cid = db.session.scalar(db.select(Category.id))
    app.config.update(APP_BASE_URL='https://desk.example.test', TELEGRAM_BOT_TOKEN='***')
    signin('employee')
    assert client.post('/tickets/new', data={'title': 'Satu alert', 'description': 'Konkurensi', 'category_id': cid}).status_code == 302
    calls = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    def fake_send(*args):
        with lock:
            calls.append(args)
        time.sleep(0.2)
        return 42
    monkeypatch.setattr(tg, 'send_message', fake_send)
    def worker():
        with app.app_context():
            barrier.wait(timeout=10)
            return tg.process_outbox(limit=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(outcomes) == [0, 1]
    assert len(calls) == 1
    with app.app_context():
        row = db.session.scalar(db.select(TelegramOutbox))
        assert row.state == 'sent' and row.attempts == 1
