"""Read local initial admin credentials from stdin without logging secrets."""
import json
import sys
from helpdesk import create_app, db
from helpdesk.models import User

credentials = json.load(sys.stdin)
app = create_app()
with app.app_context():
    existing = db.session.scalar(db.select(User).where(User.role == 'admin', User.active.is_(True)))
    if existing:
        print('An active admin already exists; no accounts changed.')
    else:
        result = app.test_cli_runner().invoke(args=['create-admin'], input='\n'.join([credentials['email'], credentials['name'], credentials['password'], credentials['password']])+'\n')
        if result.exit_code:
            raise RuntimeError('Initial admin CLI failed; secret output suppressed')
        print('Initial admin created using Flask CLI; credentials stored privately on host.')
