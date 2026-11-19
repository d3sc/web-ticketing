import click
from flask.cli import with_appcontext
from . import db
from .models import User, Category
from sqlalchemy.exc import IntegrityError


@click.command('create-admin')
@click.option('--email', prompt=True)
@click.option('--name', prompt=True)
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True)
@with_appcontext
def create_admin(email, name, password):
    import re
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(email)>254 or not name.strip() or len(name)>100 or not 12<=len(password)<=128:
        raise click.ClickException('Email/nama tidak valid atau kata sandi kurang dari 12 karakter.')
    user = User(email=email.strip().lower(), name=name.strip(), role='admin')
    user.set_password(password)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise click.ClickException('Email sudah digunakan.')
    click.echo('Administrator dibuat.')


@click.command('seed-categories')
@with_appcontext
def seed_categories():
    for code,name in [('Network','Jaringan'),('Hardware','Perangkat Keras'),('Accounts and Access','Akun dan Akses'),('Applications','Aplikasi')]:
        if not db.session.scalar(db.select(Category).where(Category.code==code)):
            db.session.add(Category(code=code,name=name))
    db.session.commit()
    click.echo('Kategori tersedia (idempoten).')
