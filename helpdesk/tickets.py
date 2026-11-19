from flask import Blueprint, render_template, request, abort, redirect, url_for
from flask_login import login_required, current_user
from . import db
from .models import Ticket, Category, User, TicketComment, TicketEvent, utcnow
from .forms import TicketForm, ReplyForm

bp = Blueprint('tickets', __name__)
STATUSES = {'open':'Terbuka', 'in_progress':'Diproses', 'resolved':'Terselesaikan', 'closed':'Ditutup'}
PRIORITIES = {'low':'Rendah', 'normal':'Normal', 'high':'Tinggi'}
TRANSITIONS = {'open': {'in_progress'}, 'in_progress': {'resolved'}, 'resolved': {'in_progress','closed'}, 'closed': set()}


def visible():
    query = db.select(Ticket)
    if current_user.role == 'employee':
        query = query.where(Ticket.creator_id == current_user.id)
    return query


def get_ticket(tid, lock=False):
    query = db.select(Ticket).where(Ticket.id == tid)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    ticket = db.session.scalar(query)
    if ticket is None:
        abort(404)
    if current_user.role == 'employee' and ticket.creator_id != current_user.id:
        abort(403)
    return ticket


def operator(ticket):
    if current_user.role != 'admin' and not (current_user.role == 'it' and ticket.assignee_id == current_user.id):
        abort(403)


def event(ticket, kind, detail):
    db.session.add(TicketEvent(ticket_id=ticket.id, actor_id=current_user.id, kind=kind, detail=detail))
    ticket.updated_at = utcnow()


def done(ticket):
    db.session.commit()
    return redirect(url_for('tickets.detail', tid=ticket.id))


@bp.get('/')
@login_required
def dashboard():
    if current_user.role != 'employee':
        return redirect(url_for('tickets.queue'))
    return render_listing('tickets.dashboard')


@bp.get('/tickets')
@login_required
def queue():
    if current_user.role not in ('it', 'admin'):
        abort(403)
    return render_listing('tickets.queue')


def render_listing(list_endpoint):
    query = visible()
    counts = dict(db.session.execute(query.with_only_columns(Ticket.status, db.func.count()).group_by(Ticket.status)).all())
    is_employee = current_user.role == 'employee'
    filters = {key: request.args.get(key, '').strip() for key in ('q', 'status', 'priority', 'category_id', 'assignee_id')}
    q = filters['q'][:200]
    if q:
        escaped = q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        conditions = [Ticket.title.ilike(f'%{escaped}%', escape='\\')]
        if q.upper().startswith('IT-') and q[3:].isdigit():
            conditions.append(Ticket.id == int(q[3:]))
        query = query.where(db.or_(*conditions))
    for key in ('status','priority','category_id','assignee_id'):
        val = filters[key]
        if val:
            if key == 'status' and val not in STATUSES:
                abort(400)
            if key == 'priority' and val not in PRIORITIES:
                abort(400)
            if key in ('category_id','assignee_id'):
                if key == 'assignee_id' and val == 'unassigned':
                    query = query.where(Ticket.assignee_id.is_(None))
                    continue
                if not val.isdigit():
                    abort(400)
                val = int(val)
            query = query.where(getattr(Ticket,key) == val)
    page = max(1, request.args.get('page',1,type=int) or 1)
    pagination = db.paginate(query.order_by(Ticket.created_at.desc(), Ticket.id.desc()), page=page, per_page=20, error_out=False)
    def pagination_url(page):
        return url_for(list_endpoint, **{key: value for key, value in filters.items() if value}, page=page)

    return render_template(
        'queue.html', pagination=pagination, counts=counts,
        categories=db.session.scalars(db.select(Category).order_by(Category.name)).all(),
        agents=[] if is_employee else db.session.scalars(db.select(User).where(User.role=='it').order_by(User.name)).all(),
        is_employee=is_employee, list_endpoint=list_endpoint,
        has_filters=any(filters.values()), total_tickets=sum(counts.values()),
        pagination_url=pagination_url,
    )


@bp.route('/tickets/new', methods=['GET','POST'])
@login_required
def new():
    form = TicketForm()
    form.category_id.choices = [(c.id,c.name) for c in db.session.scalars(db.select(Category).where(Category.active.is_(True)).order_by(Category.name))]
    if form.validate_on_submit():
        ticket = Ticket(title=form.title.data.strip(), description=form.description.data.strip(), category_id=form.category_id.data, priority=form.priority.data, creator_id=current_user.id)
        if not ticket.title or not ticket.description:
            abort(400)
        db.session.add(ticket)
        db.session.flush()
        event(ticket, 'created', 'Tiket dibuat')
        return done(ticket)
    return render_template('new_ticket.html', form=form), (400 if request.method=='POST' else 200)


@bp.get('/tickets/<int:tid>')
@login_required
def detail(tid):
    ticket = get_ticket(tid)
    agents = db.session.scalars(db.select(User).where(User.role=='it', User.active.is_(True)).order_by(User.name)).all() if current_user.role=='admin' else []
    return render_template('detail.html', ticket=ticket, form=ReplyForm(), agents=agents, transitions=TRANSITIONS[ticket.status])


@bp.post('/tickets/<int:tid>/claim')
@login_required
def claim(tid):
    if current_user.role != 'it':
        abort(403)
    agent = db.session.scalar(db.select(User).where(User.id==current_user.id).with_for_update().execution_options(populate_existing=True))
    if not agent or not agent.active or agent.role != 'it':
        abort(403)
    # A single conditional UPDATE is the arbitration point, including on SQLite.
    result = db.session.execute(db.update(Ticket).where(Ticket.id==tid, Ticket.assignee_id.is_(None), Ticket.status!='closed').values(assignee_id=current_user.id, updated_at=utcnow()))
    if result.rowcount != 1:
        db.session.rollback()
        if db.session.get(Ticket,tid) is None:
            abort(404)
        abort(409, 'Tiket sudah diambil atau ditutup.')
    ticket = db.session.get(Ticket,tid)
    event(ticket,'assignment',f'Diambil oleh {current_user.name}')
    return done(ticket)


@bp.post('/tickets/<int:tid>/reply')
@login_required
def reply(tid):
    ticket = get_ticket(tid, lock=True)
    if current_user.role != 'employee':
        operator(ticket)
    if ticket.status == 'closed':
        abort(409, 'Tiket sudah ditutup.')
    form = ReplyForm()
    if not form.validate_on_submit() or not form.body.data.strip():
        abort(400)
    db.session.add(TicketComment(ticket_id=tid,actor_id=current_user.id,body=form.body.data.strip()))
    event(ticket,'comment','Balasan ditambahkan')
    return done(ticket)


@bp.post('/tickets/<int:tid>/update')
@login_required
def update(tid):
    ticket = get_ticket(tid, lock=True)
    operator(ticket)
    status = request.form.get('status',ticket.status)
    priority = request.form.get('priority',ticket.priority)
    if status not in STATUSES or priority not in PRIORITIES:
        abort(400)
    if status != ticket.status and status not in TRANSITIONS[ticket.status]:
        abort(409, 'Perubahan status tidak diizinkan.')
    if ticket.status == 'closed' and priority != ticket.priority:
        abort(409)
    if status != ticket.status or priority != ticket.priority:
        event(ticket,'update',f'Status: {ticket.status} → {status}; prioritas: {ticket.priority} → {priority}')
        ticket.status, ticket.priority = status, priority
    return done(ticket)


@bp.post('/tickets/<int:tid>/assign')
@login_required
def assign(tid):
    if current_user.role != 'admin':
        abort(403)
    ticket = get_ticket(tid, lock=True)
    aid = request.form.get('assignee_id',type=int)
    # Lock the account too, serializing assignment against deactivation.
    agent = db.session.scalar(db.select(User).where(User.id==aid).with_for_update().execution_options(populate_existing=True))
    if not agent or not agent.active or agent.role != 'it':
        abort(400)
    if ticket.assignee_id != aid:
        event(ticket,'assignment',f'Penugasan: {ticket.assignee_id or "—"} → {agent.name} (#{aid})')
        ticket.assignee_id = aid
    return done(ticket)
