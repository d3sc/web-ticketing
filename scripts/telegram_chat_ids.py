"""Cetak ID chat bot khusus Helpdesk tanpa mencetak token atau URL API."""
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def main():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        print('TELEGRAM_BOT_TOKEN belum dikonfigurasi.', file=sys.stderr)
        return 1
    try:
        request = Request('https://api.telegram.org/bot' + token + '/getUpdates',
                          data=json.dumps({'timeout': 0, 'allowed_updates': ['message', 'my_chat_member']}).encode(),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=10) as response:
            body = json.loads(response.read(1048576))
        if not body.get('ok'):
            print('Telegram menolak getUpdates; periksa token dan pastikan bot tidak memakai webhook.', file=sys.stderr)
            return 1
    except (HTTPError, URLError, OSError, ValueError):
        print('Gagal membaca getUpdates. Periksa koneksi, token, dan pastikan bot khusus ini tidak memakai webhook/poller lain.', file=sys.stderr)
        return 1
    chats = {}
    for update in body.get('result', []):
        for kind in ['message', 'my_chat_member']:
            chat = update.get(kind, {}).get('chat', {})
            if 'id' in chat:
                chats[str(chat['id'])] = chat.get('title') or chat.get('first_name') or chat.get('type', '')
    if not chats:
        print('Belum ada chat. Kirim /start ke bot, atau tambahkan bot ke grup lalu kirim /start@NamaBot. Jalankan lagi.')
        return 1
    for chat_id, name in chats.items():
        print(f'{chat_id}: {name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
