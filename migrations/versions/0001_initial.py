"""Initial helpdesk schema, explicit and independent of application metadata."""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('name',sa.String(100),nullable=False),
        sa.Column('email',sa.String(254),nullable=False),
        sa.Column('password_hash',sa.String(255),nullable=False),
        sa.Column('role',sa.String(20),nullable=False),
        sa.Column('active',sa.Boolean(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.UniqueConstraint('email'),
        sa.CheckConstraint("role IN ('employee','it','admin')",name='user_role'),
        mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('categories',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('code',sa.String(50),nullable=False),
        sa.Column('name',sa.String(100),nullable=False),
        sa.Column('active',sa.Boolean(),nullable=False),
        sa.UniqueConstraint('code'),mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_table('tickets',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('title',sa.String(200),nullable=False),
        sa.Column('description',sa.Text(),nullable=False),
        sa.Column('creator_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('category_id',sa.Integer(),sa.ForeignKey('categories.id'),nullable=False),
        sa.Column('assignee_id',sa.Integer(),sa.ForeignKey('users.id')),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('priority',sa.String(10),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        sa.Column('updated_at',sa.DateTime(),nullable=False),
        sa.CheckConstraint("status IN ('open','in_progress','resolved','closed')",name='ticket_status'),
        sa.CheckConstraint("priority IN ('low','normal','high')",name='ticket_priority'),
        mysql_engine='InnoDB',mysql_charset='utf8mb4')
    for name in ('creator_id','category_id','assignee_id','status','priority'):
        op.create_index(f'ix_tickets_{name}','tickets',[name])
    op.create_table('ticket_comments',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('ticket_id',sa.Integer(),sa.ForeignKey('tickets.id'),nullable=False),
        sa.Column('actor_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('body',sa.Text(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_ticket_comments_ticket_id','ticket_comments',['ticket_id'])
    op.create_table('ticket_events',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('ticket_id',sa.Integer(),sa.ForeignKey('tickets.id'),nullable=False),
        sa.Column('actor_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('kind',sa.String(30),nullable=False),
        sa.Column('detail',sa.Text(),nullable=False),
        sa.Column('created_at',sa.DateTime(),nullable=False),
        mysql_engine='InnoDB',mysql_charset='utf8mb4')
    op.create_index('ix_ticket_events_ticket_id','ticket_events',['ticket_id'])


def downgrade():
    for table in ('ticket_events','ticket_comments','tickets','categories','users'):
        op.drop_table(table)
