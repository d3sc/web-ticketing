from flask import Blueprint, render_template, redirect, url_for, session
from flask_login import login_user, logout_user, login_required, current_user
from . import db
from .forms import LoginForm
from .models import User

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(db.select(User).where(User.email == form.email.data.strip().lower()))
        if user and user.active and user.check_password(form.password.data):
            session.clear()
            login_user(user)
            return redirect(url_for('tickets.dashboard' if user.role == 'employee' else 'tickets.queue'))
        form.password.errors.append('Email atau kata sandi salah, atau akun tidak aktif.')
    from flask import request
    return render_template('login.html', form=form), (400 if request.method == 'POST' else 200)


@bp.post('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('auth.login'))
