"""Transactional Telegram delivery (at least once).

A worker holds one InnoDB row lock across a bounded HTTP request. A crash after
Telegram accepts a message but before commit can cause a duplicate; sent rows
are never automatically resent. Run workers against MySQL 8+ for SKIP LOCKED;
SQLite is supported for isolated tests, not concurrent production workers.
"""
import ipaddress
import json
import re
import time
from pathlib import Path
from datetime import timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import click
from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy.orm import Session

from . import db
from .models import TelegramOutbox, TelegramSettings, utcnow

MAX_ATTEMPTS = 8
HTTP_TIMEOUT = 10


class TelegramDeliveryError(Exception):
    """Only application-controlled Indonesian messages may cross this boundary."""

    def __init__(self, message, transient=False, retry_after=None):
        super().__init__(message)
        self.transient = transient
        self.retry_after = retry_after


def valid_chat_id(value):
    return (isinstance(value, str) and len(value) <= 32
            and re.fullmatch(r'-?[1-9][0-9]*', value) is not None)


def valid_base_url(value):
    if not isinstance(value, str) or not value or len(value) > 1900:
        return False
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value:
        return False
    try:
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme not in ('http', 'https') or not host or
                parts.username is not None or parts.password is not None or
                '?' in value or '#' in value or host.rstrip('.').lower() == 'localhost' or
                host.lower().endswith('.localhost')):
            return False
        parts.port  # Validate malformed/out-of-range ports without using them.
        try:
            if ipaddress.ip_address(host).is_loopback or ipaddress.ip_address(host).is_unspecified:
                return False
        except ValueError:
            pass
        return True
    except ValueError:
        return False


def queue_new_ticket(ticket):
    """Add a snapshot to the caller's transaction; never commit or perform HTTP."""
    settings = db.session.get(TelegramSettings, 1)
    if not settings or not settings.enabled or not valid_chat_id(settings.chat_id):
        return None
    base = current_app.config.get('APP_BASE_URL', '')
    url = ''
    if valid_base_url(base):
        # Build from the actual route without creating a request context: its
        # teardown would roll back the caller's ticket creation transaction.
        path = current_app.url_map.bind('').build('tickets.detail', {'tid': ticket.id})
        url = base.rstrip('/') + path
    created = ticket.created_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Jakarta'))
    priority = {'low': 'Rendah', 'normal': 'Normal', 'high': 'Tinggi'}.get(ticket.priority, 'Normal')
    text = (f'Tiket baru masuk\nNomor: {ticket.reference}\nJudul: {ticket.title}\n'
            f'Kategori: {ticket.category.name}\nPrioritas: {priority}\n'
            f'Waktu: {created:%d/%m/%Y %H:%M} WIB')
    if url:
        text += '\n\nBuka Tiket: ' + url
    row = TelegramOutbox(ticket_id=ticket.id, chat_id=settings.chat_id, text=text, url=url)
    db.session.add(row)
    return row


def _transport(token, payload):
    """Small replaceable transport. Never log its URL, body, or exceptions."""
    request = Request(f'https://api.telegram.org/bot{token}/sendMessage',
                      data=json.dumps(payload).encode('utf-8'),
                      headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read(65536))


def _http_error(code, body):
    if code == 429:
        parameters = body.get('parameters', {}) if isinstance(body, dict) else {}
        wait = parameters.get('retry_after') if isinstance(parameters, dict) else None
        if not isinstance(wait, int) or isinstance(wait, bool) or wait < 0:
            wait = None
        return TelegramDeliveryError('Batas permintaan Telegram tercapai; akan dicoba lagi.', True, wait)
    if code >= 500:
        return TelegramDeliveryError('Layanan Telegram sedang bermasalah; akan dicoba lagi.', True)
    messages = {
        400: 'Permintaan Telegram ditolak; periksa ID chat dan isi pesan.',
        401: 'Token bot Telegram tidak valid; periksa konfigurasi token.',
        403: 'Bot tidak diizinkan mengirim pesan; tambahkan bot dan periksa izin chat.',
    }
    return TelegramDeliveryError(messages.get(code, 'Pengiriman Telegram ditolak; periksa konfigurasi.'))


def _invalid_button(body):
    description = body.get('description', '') if isinstance(body, dict) else ''
    if not isinstance(description, str):
        return False
    description = description.lower()
    return ('button' in description and 'url' in description
            and any(word in description for word in ('invalid', 'wrong', 'unsupported', 'not allowed')))


def send_message(chat_id, text, url=''):
    """Send plain text with a URL fallback; return Telegram's integer message ID."""
    token = current_app.config.get('TELEGRAM_BOT_TOKEN', '')
    if not isinstance(token, str) or not token.strip():
        raise TelegramDeliveryError('TELEGRAM_BOT_TOKEN belum dikonfigurasi.')
    if not valid_chat_id(chat_id):
        raise TelegramDeliveryError('ID chat Telegram tidak valid.')
    payload = {'chat_id': chat_id, 'text': text}
    if url:
        if not valid_base_url(url):
            raise TelegramDeliveryError('APP_BASE_URL tidak valid; periksa alamat aplikasi.')
        if url not in text:
            payload['text'] += '\n' + url
        payload['reply_markup'] = {'inline_keyboard': [[{'text': 'Buka Tiket', 'url': url}]]}
    for attempt in range(2):
        try:
            try:
                body = _transport(token.strip(), payload)
            except HTTPError as exc:
                code = exc.code
                try:
                    body = json.loads(exc.read(65536))
                except (ValueError, OSError):
                    body = {}
            else:
                if not isinstance(body, dict):
                    raise TelegramDeliveryError('Respons Telegram tidak valid; akan dicoba lagi.', True)
                if body.get('ok') is True:
                    result = body.get('result')
                    message_id = result.get('message_id') if isinstance(result, dict) else None
                    if isinstance(message_id, int) and not isinstance(message_id, bool) and message_id > 0:
                        return message_id
                    raise TelegramDeliveryError('Respons Telegram tidak valid; akan dicoba lagi.', True)
                code = body.get('error_code', 502)
                if not isinstance(code, int):
                    code = 502
            if code == 400 and attempt == 0 and 'reply_markup' in payload and _invalid_button(body):
                payload = {k: v for k, v in payload.items() if k != 'reply_markup'}
                continue
            raise _http_error(code, body)
        except (URLError, TimeoutError, OSError, ValueError):
            raise TelegramDeliveryError('Koneksi atau respons Telegram bermasalah; akan dicoba lagi.', True) from None


def process_outbox(limit=20):
    """Process committed rows only; return attempted count (paused rows excluded)."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('Batas worker harus antara 1 dan 100.')
    processed = 0
    for _ in range(limit):
        # Independent session: never flush/commit the ticket creator's transaction.
        with Session(db.engine) as session, session.begin():
            settings = session.get(TelegramSettings, 1)
            if not settings or not settings.enabled:
                break
            row = session.scalar(db.select(TelegramOutbox).where(
                TelegramOutbox.state == 'pending', TelegramOutbox.available_at <= utcnow()
            ).order_by(TelegramOutbox.available_at, TelegramOutbox.id).limit(1)
                .with_for_update(skip_locked=True))
            if row is None:
                break
            row.attempts += 1
            try:
                if not row.url or not valid_base_url(row.url):
                    raise TelegramDeliveryError('APP_BASE_URL belum dikonfigurasi atau tidak valid.')
                send_message(row.chat_id, row.text, row.url)
            except TelegramDeliveryError as exc:
                row.last_error = str(exc)
                if exc.transient and row.attempts < MAX_ATTEMPTS:
                    delay = max(5 * 2 ** (row.attempts - 1), exc.retry_after or 0)
                    # Never shorten Telegram's retry_after. Values beyond the
                    # supported datetime range require operator review instead.
                    try:
                        row.available_at = utcnow() + timedelta(seconds=delay)
                    except OverflowError:
                        row.state = 'failed'
                        row.last_error = 'Nilai retry_after Telegram di luar rentang waktu; periksa antrean dan konfigurasi.'
                else:
                    row.state = 'failed'
            else:
                row.state = 'sent'
                row.sent_at = utcnow()
                row.last_error = None
            processed += 1
    # Expire only clean instances; do not discard a caller's uncommitted edits.
    if not db.session.new and not db.session.dirty and not db.session.deleted:
        db.session.expire_all()
    return processed


def register_cli(app):
    @click.command('telegram-worker')
    @click.option('--once', is_flag=True, help='Proses satu batch lalu berhenti.')
    @click.option('--limit', type=click.IntRange(1, 100), default=20, show_default=True)
    @with_appcontext
    def worker(once, limit):
        """Kirim antrean Telegram; polling setiap lima detik secara bawaan."""
        while True:
            Path('/tmp/telegram-worker-heartbeat').touch()
            count = process_outbox(limit)
            click.echo(json.dumps({'processed': count}))
            if once:
                return
            time.sleep(5)
    app.cli.add_command(worker)
