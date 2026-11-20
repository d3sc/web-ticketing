from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SelectField, BooleanField
from wtforms.validators import DataRequired, Length, Regexp, EqualTo


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Password administrator saat ini', validators=[DataRequired()], render_kw={'autocomplete': 'current-password'})
    password = PasswordField('Password baru', validators=[DataRequired(), Length(min=12, max=128, message='Password harus terdiri dari 12–128 karakter.')], render_kw={'autocomplete': 'new-password'})
    confirm_password = PasswordField('Konfirmasi password baru', validators=[DataRequired(), EqualTo('password', message='Konfirmasi password tidak sama.')], render_kw={'autocomplete': 'new-password'})


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Length(max=254)])
    password = PasswordField('Kata sandi', validators=[DataRequired()])


class TicketForm(FlaskForm):
    title = StringField('Judul', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Deskripsi', validators=[DataRequired(), Length(max=20000)])
    category_id = SelectField('Kategori', coerce=int, validators=[DataRequired()])
    priority = SelectField('Prioritas', choices=[('low','Rendah'), ('normal','Normal'), ('high','Tinggi')], default='normal', validate_choice=False)

    def validate_priority(self, field):
        if field.data not in ('low', 'normal', 'high'):
            from wtforms.validators import ValidationError
            raise ValidationError('Prioritas tidak valid.')



class ReplyForm(FlaskForm):
    body = TextAreaField('Balasan', validators=[DataRequired(), Length(max=20000)])


class UserForm(FlaskForm):
    name = StringField('Nama', validators=[DataRequired(), Length(max=100)])
    email = StringField('Email', validators=[DataRequired(), Length(max=254), Regexp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')])
    password = PasswordField('Kata sandi', validators=[DataRequired(), Length(min=12, max=128)])
    role = SelectField('Peran', choices=[('employee','Karyawan'),('it','Agen IT'),('admin','Administrator')])


class TelegramSettingsForm(FlaskForm):
    enabled = BooleanField('Aktifkan notifikasi tiket baru')
    chat_id = StringField('Chat ID Tujuan', filters=[lambda value: value.strip() if value else ''])

    def validate_chat_id(self, field):
        from .telegram import valid_chat_id
        from wtforms.validators import ValidationError
        if (self.enabled.data or field.data) and not valid_chat_id(field.data):
            raise ValidationError('Chat ID harus berupa angka positif atau negatif, bukan nol (maksimal 32 karakter).')


class CategoryForm(FlaskForm):
    code = StringField('Kode Inggris', validators=[DataRequired(), Length(max=50), Regexp(r'^[A-Za-z][A-Za-z0-9_-]*$')])
    name = StringField('Nama', validators=[DataRequired(), Length(max=100)])
