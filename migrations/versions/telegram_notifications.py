"""Telegram notification settings and transactional outbox."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

OUTBOX_TIME = sa.DateTime().with_variant(DATETIME(fsp=6), 'mysql')

revision = 'telegram_notifications'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    settings = op.create_table(
        'telegram_settings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('chat_id', sa.String(32), nullable=False, server_default=''),
        sa.CheckConstraint('id = 1', name='telegram_settings_singleton'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.bulk_insert(settings, [{'id': 1, 'enabled': False, 'chat_id': ''}])
    op.create_table(
        'telegram_outbox',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('tickets.id'), nullable=False),
        sa.Column('chat_id', sa.String(32), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('url', sa.String(2048), nullable=False),
        sa.Column('state', sa.String(10), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('available_at', OUTBOX_TIME, nullable=False),
        sa.Column('sent_at', OUTBOX_TIME),
        sa.Column('last_error', sa.Text()),
        sa.Column('created_at', OUTBOX_TIME, nullable=False),
        sa.UniqueConstraint('ticket_id'),
        sa.CheckConstraint("state IN ('pending','sent','failed')", name='telegram_outbox_state'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4')
    op.create_index('ix_telegram_outbox_due', 'telegram_outbox', ['state', 'available_at', 'id'])


def downgrade():
    op.drop_table('telegram_outbox')
    op.drop_table('telegram_settings')
