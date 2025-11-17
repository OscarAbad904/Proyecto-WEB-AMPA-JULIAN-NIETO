from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, PasswordField, StringField, SubmitField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional


class LoginForm(FlaskForm):
    email = EmailField("Correo", validators=[DataRequired(), Email()])
    password = PasswordField("Contraseña", validators=[DataRequired(), Length(min=8)])
    remember_me = BooleanField("Recordarme")
    submit = SubmitField("Entrar")


class RegisterForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(min=3, max=64)])
    email = EmailField("Correo", validators=[DataRequired(), Email()])
    password = PasswordField("Contraseña", validators=[DataRequired(), Length(min=8)])
    password_confirm = PasswordField(
        "Repite la contraseña", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Crear cuenta")


class RecoverForm(FlaskForm):
    email = EmailField("Correo electrónico", validators=[DataRequired(), Email()])
    submit = SubmitField("Enviar código SMS")


class ResetPasswordForm(FlaskForm):
    email = EmailField("Correo electrónico", validators=[DataRequired(), Email()])
    code = StringField("Código SMS", validators=[DataRequired(), Length(min=6, max=6)])
    password = PasswordField("Nueva contraseña", validators=[DataRequired(), Length(min=8)])
    password_confirm = PasswordField(
        "Repite la contraseña", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Cambiar contraseña")


class NewMemberForm(FlaskForm):
    first_name = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=64)])
    last_name = StringField("Apellidos", validators=[DataRequired(), Length(min=2, max=64)])
    email = EmailField("Correo electrónico", validators=[DataRequired(), Email()])
    phone_number = StringField("Teléfono", validators=[DataRequired(), Length(min=6, max=32)])
    address = StringField("Dirección", validators=[DataRequired(), Length(min=4, max=255)])
    city = StringField("Ciudad", validators=[DataRequired(), Length(min=2, max=128)])
    postal_code = StringField("Código postal", validators=[Optional(), Length(min=3, max=10)])
    member_number = StringField("Número de socio", validators=[Optional(), Length(max=32)])
    year = IntegerField("Año", validators=[Optional()], default=None)
    submit = SubmitField("Dar de alta")
