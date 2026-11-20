"""Isolated browser fixture server. Never use against the live database."""
import os
from sqlalchemy.engine import make_url
from helpdesk import create_app
from helpdesk import telegram as tg

url = make_url(os.environ['DATABASE_URL'])
assert url.database == 'helpdesk_test' and url.host == 'test-db'
app = create_app({'TELEGRAM_BOT_TOKEN': 'fixture-not-a-real-token',
                  'APP_BASE_URL': 'http://helpdesk.test:5018'})
# Test-server-only transport; the production app has no mock mode or bypass route.
tg._transport = lambda *args: {'ok': True, 'result': {'message_id': 99}}
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)
