import os
from datetime import timezone
from zoneinfo import ZoneInfo
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login = LoginManager()
csrf = CSRFProtect()


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(SECRET_KEY=os.environ.get('SECRET_KEY'), SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite://'), SQLALCHEMY_TRACK_MODIFICATIONS=False, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=1024*1024)
    app.config.update(config or {})
    if not app.config.get('SECRET_KEY'):
        if app.testing:
            from secrets import token_hex
            app.config['SECRET_KEY'] = token_hex(32)
        else:
            raise RuntimeError('SECRET_KEY wajib dikonfigurasi; tidak ada kata sandi bawaan.')
    db.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app)
    csrf.init_app(app)
    login.login_view = 'auth.login'
    @app.get('/health')
    def health():
        db.session.execute(db.text('SELECT 1'))
        return {'status': 'ok'}
    @app.template_filter('jakarta')
    def jakarta(value):
        return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Jakarta')).strftime('%d %b %Y, %H:%M WIB') if value else '—'
    from .models import User
    from .auth import bp as auth_bp
    from .tickets import bp as tickets_bp, STATUSES, PRIORITIES
    @app.template_filter('event_detail')
    def event_detail(event):
        if event.kind != 'update':
            return event.detail
        import re
        labels = {**STATUSES, **PRIORITIES}
        return re.sub(r'\b(open|in_progress|resolved|closed|low|normal|high)\b', lambda match: labels[match.group()], event.detail)
    from .admin import bp as admin_bp
    from .cli import create_admin, seed_categories
    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(admin_bp)
    app.cli.add_command(create_admin)
    app.cli.add_command(seed_categories)

    @login.user_loader
    def load_user(uid):
        try:
            user = db.session.get(User, int(uid))
        except (ValueError, TypeError):
            return None
        return user if user and user.active else None

    @app.context_processor
    def labels():
        return dict(statuses=STATUSES, priorities=PRIORITIES)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    def error(exc):
        db.session.rollback()
        return __import__('flask').render_template('error.html', error=exc), exc.code

    @app.teardown_request
    def rollback_uncommitted(exc):
        db.session.rollback()

    return app
