from datetime import datetime, timezone
from sqlalchemy.dialects.mysql import DATETIME

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from . import db

OUTBOX_TIME = db.DateTime().with_variant(DATETIME(fsp=6), 'mysql')


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='employee')
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (db.CheckConstraint("role IN ('employee','it','admin')", name='user_role'),)

    @property
    def is_active(self):
        return self.active

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class Ticket(db.Model):
    __tablename__ = 'tickets'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False, index=True)
    assignee_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    status = db.Column(db.String(20), nullable=False, default='open', index=True)
    priority = db.Column(db.String(10), nullable=False, default='normal', index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    creator = db.relationship(User, foreign_keys=[creator_id])
    assignee = db.relationship(User, foreign_keys=[assignee_id])
    category = db.relationship(Category)
    comments = db.relationship('TicketComment', order_by='TicketComment.id', backref='ticket')
    events = db.relationship('TicketEvent', order_by='TicketEvent.id', backref='ticket')
    __table_args__ = (
        db.CheckConstraint("status IN ('open','in_progress','resolved','closed')", name='ticket_status'),
        db.CheckConstraint("priority IN ('low','normal','high')", name='ticket_priority'),
    )

    @property
    def reference(self):
        return f'IT-{self.id:06d}'


class TicketComment(db.Model):
    __tablename__ = 'ticket_comments'
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    actor = db.relationship(User)


class TicketEvent(db.Model):
    __tablename__ = 'ticket_events'
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    detail = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    actor = db.relationship(User)


class TelegramSettings(db.Model):
    __tablename__ = 'telegram_settings'
    id = db.Column(db.Integer, primary_key=True, default=1, autoincrement=False)
    enabled = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    chat_id = db.Column(db.String(32), nullable=False, default='', server_default='')
    __table_args__ = (db.CheckConstraint('id = 1', name='telegram_settings_singleton'),)


class TelegramOutbox(db.Model):
    __tablename__ = 'telegram_outbox'
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False, unique=True)
    chat_id = db.Column(db.String(32), nullable=False)
    text = db.Column(db.Text, nullable=False)
    url = db.Column(db.String(2048), nullable=False, default='')
    state = db.Column(db.String(10), nullable=False, default='pending', server_default='pending')
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    available_at = db.Column(OUTBOX_TIME, nullable=False, default=utcnow)
    sent_at = db.Column(OUTBOX_TIME)
    last_error = db.Column(db.Text)
    created_at = db.Column(OUTBOX_TIME, nullable=False, default=utcnow)
    __table_args__ = (
        db.CheckConstraint("state IN ('pending','sent','failed')", name='telegram_outbox_state'),
        db.Index('ix_telegram_outbox_due', 'state', 'available_at', 'id'),
    )
