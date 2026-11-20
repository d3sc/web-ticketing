from functools import wraps
from flask import Blueprint, abort, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from . import db
from .models import User, Category, Ticket, TelegramSettings, TelegramOutbox
from .forms import UserForm, CategoryForm, ChangePasswordForm, TelegramSettingsForm

bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_only(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != 'admin':
            abort(403)
        return fn(*args, **kwargs)
    return wrapped


def commit():
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        abort(400, 'Email atau kode sudah digunakan.')


@bp.route('/users', methods=['GET','POST'])
@admin_only
def users():
    form = UserForm()
    if form.validate_on_submit():
        user = User(name=form.name.data.strip(), email=form.email.data.strip().lower(), role=form.role.data)
        if not user.name:
            abort(400)
        user.set_password(form.password.data)
        db.session.add(user)
        commit()
        return redirect(url_for('admin.users'))
    return render_template('users.html',form=form,users=db.session.scalars(db.select(User).order_by(User.name)).all()), (400 if request.method=='POST' else 200)


@bp.route('/users/<int:uid>/password', methods=['GET', 'POST'])
@admin_only
def change_password(uid):
    user = db.get_or_404(User, uid)
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            form.current_password.errors.append('Password administrator saat ini tidak sesuai.')
        else:
            user.set_password(form.password.data)
            commit()
            flash('Password berhasil diubah.', 'success')
            return redirect(url_for('admin.users'))
    response = render_template('change_password.html', form=form, user=user)
    return response, (400 if request.method == 'POST' else 200), {'Cache-Control': 'no-store'}


@bp.post('/users/<int:uid>')
@admin_only
def edit_user(uid):
    user = db.session.scalar(db.select(User).where(User.id==uid).with_for_update().execution_options(populate_existing=True))
    if not user:
        abort(404)
    role, active = request.form.get('role'), request.form.get('active')
    if role not in ('employee','it','admin') or active not in ('0','1'):
        abort(400)
    if uid == current_user.id and (role != 'admin' or active != '1'):
        abort(409, 'Anda tidak dapat menonaktifkan atau menurunkan peran sendiri.')
    if role != 'it' or active == '0':
        # Locking read sees the latest committed assignment under MySQL REPEATABLE READ.
        work = db.session.scalar(db.select(Ticket.id).where(Ticket.assignee_id==uid, Ticket.status!='closed').with_for_update())
        if work:
            abort(409, 'Alihkan tiket aktif sebelum mengubah agen.')
    user.role, user.active = role, active == '1'
    commit()
    return redirect(url_for('admin.users'))


@bp.route('/settings/telegram', methods=['GET', 'POST'])
@admin_only
def telegram_settings():
    from .telegram import valid_base_url
    settings = db.session.get(TelegramSettings, 1)
    form = TelegramSettingsForm(obj=settings)
    if form.validate_on_submit():
        if settings is None:
            settings = TelegramSettings(id=1)
            db.session.add(settings)
        settings.enabled, settings.chat_id = form.enabled.data, form.chat_id.data
        commit()
        flash('Pengaturan Telegram berhasil disimpan.', 'success')
        return redirect(url_for('admin.telegram_settings'))
    rows = db.session.scalars(db.select(TelegramOutbox).order_by(TelegramOutbox.id.desc()).limit(20)).all()
    return render_template('telegram_settings.html', form=form, rows=rows,
                           token_ready=bool(current_app.config.get('TELEGRAM_BOT_TOKEN')),
                           base_ready=valid_base_url(current_app.config.get('APP_BASE_URL'))), (400 if request.method == 'POST' else 200)


@bp.post('/settings/telegram/test')
@admin_only
def telegram_test():
    from .telegram import send_message, valid_chat_id, TelegramDeliveryError
    settings = db.session.get(TelegramSettings, 1)
    if not settings or not valid_chat_id(settings.chat_id):
        flash('Simpan Chat ID Tujuan yang valid terlebih dahulu.', 'danger')
    else:
        try:
            send_message(settings.chat_id, 'Pesan tes Helpdesk IT. Notifikasi Telegram berhasil terhubung.')
        except TelegramDeliveryError as exc:
            flash(str(exc), 'danger')
        else:
            flash('Pesan tes berhasil dikirim ke Chat ID Tujuan yang tersimpan.', 'success')
    return redirect(url_for('admin.telegram_settings'))


@bp.route('/categories', methods=['GET','POST'])
@admin_only
def categories():
    form = CategoryForm()
    if form.validate_on_submit():
        if not form.name.data.strip():
            abort(400)
        db.session.add(Category(code=form.code.data,name=form.name.data.strip()))
        commit()
        return redirect(url_for('admin.categories'))
    return render_template('categories.html', form=form, categories=db.session.scalars(db.select(Category).order_by(Category.name)).all()), (400 if request.method=='POST' else 200)


@bp.post('/categories/<int:cid>')
@admin_only
def edit_category(cid):
    category = db.session.get(Category,cid)
    if category is None:
        abort(404)
    name = request.form.get('name','').strip()
    active = request.form.get('active')
    if not name or len(name)>100 or active not in ('0','1'):
        abort(400)
    category.name, category.active = name, active=='1'
    commit()
    return redirect(url_for('admin.categories'))
