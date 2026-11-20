"""Boundary tests for Telegram retry scheduling."""
from tests.test_telegram_delivery import app, ticket, no_network, enqueue
from helpdesk import db
from helpdesk import telegram as tg


def test_excessive_retry_after_never_retries_earlier(app, ticket, monkeypatch):
    row = enqueue(ticket)
    def fail(*args):
        raise tg.TelegramDeliveryError('Batas permintaan tercapai.', transient=True, retry_after=2**80)
    monkeypatch.setattr(tg, 'send_message', fail)
    assert tg.process_outbox() == 1
    db.session.rollback()
    assert row.state == 'failed'
    assert 'retry_after' in row.last_error
