from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    HiddenField,
)
from wtforms.fields import DateField, EmailField, FileField
from wtforms.validators import AnyOf, DataRequired, Email, EqualTo, Length, Optional, URL

EVENT_CATEGORY_CHOICES = [
    ("actividades", "Actividades"),
    ("talleres", "Talleres"),
    ("reuniones", "Reuniones"),
    ("comunidad", "Comunidad"),
    ("otro", "Otro"),
]
EVENT_CATEGORY_LABELS = {key: label for key, label in EVENT_CATEGORY_CHOICES}


class LoginForm(FlaskForm):
    email = EmailField("Correo", validators=[DataRequired(), Email()])
    password = PasswordField("Contraseña", validators=[DataRequired(), Length(min=8)])
    remember_me = BooleanField("Recordarme")
    submit = SubmitField("Entrar")


class RegisterForm(FlaskForm):
    first_name = StringField("Nombre", validators=[DataRequired(), Length(min=2, max=64)])
    last_name = StringField("Apellidos", validators=[DataRequired(), Length(min=2, max=64)])
    email = EmailField("Correo", validators=[DataRequired(), Email(), Length(max=256)])
    phone_number = StringField("Teléfono", validators=[Optional(), Length(min=6, max=32)])
    privacy_accepted = BooleanField(
        "He leído y acepto la política de privacidad",
        validators=[DataRequired(message="No puedes registrarte sin aceptar la política de privacidad.")],
    )
    submit = SubmitField("Solicitar alta")


class RecoverForm(FlaskForm):
    email = EmailField("Correo electrónico", validators=[DataRequired(), Email()])
    submit = SubmitField("Enviar código SMS")


class ResetPasswordForm(FlaskForm):
    email = EmailField("Correo electrónico", validators=[DataRequired(), Email()])
    code = StringField("Código SMS", validators=[DataRequired(), Length(min=6, max=6)])
    password = PasswordField("Nueva contraseña", validators=[DataRequired(), Length(min=8)])
    password_confirm = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("password")],
    )
    submit = SubmitField("Cambiar contraseña")


class ResendVerificationForm(FlaskForm):
    email = EmailField("Correo electrónico", validators=[DataRequired(), Email()])
    submit = SubmitField("Reenviar verificación")


class SetPasswordForm(FlaskForm):
    password = PasswordField("Nueva contraseña", validators=[DataRequired(), Length(min=8)])
    password_confirm = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("password")],
    )
    submit = SubmitField("Guardar contraseña")


class UpdatePhoneForm(FlaskForm):
    phone_number = StringField("Teléfono", validators=[Optional(), Length(min=6, max=32)])
    submit_phone = SubmitField("Guardar teléfono")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Contraseña actual", validators=[DataRequired(), Length(min=8)])
    new_password = PasswordField("Nueva contraseña", validators=[DataRequired(), Length(min=8)])
    new_password_confirm = PasswordField(
        "Repite la contraseña",
        validators=[DataRequired(), EqualTo("new_password")],
    )
    submit_password = SubmitField("Cambiar contraseña")


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


class SuggestionForm(FlaskForm):
    title = StringField("Título", validators=[DataRequired(), Length(max=255)])
    category = SelectField(
        "Categoría",
        choices=[
            ("infraestructura", "Infraestructura"),
            ("actividades", "Actividades"),
            ("otro", "Otro"),
        ],
        validators=[DataRequired()],
    )
    body = TextAreaField("Detalle", validators=[DataRequired(), Length(min=10)])
    attachment = FileField("Adjuntar archivo (opcional)")
    submit = SubmitField("Enviar sugerencia")


class CommissionDiscussionForm(FlaskForm):
    title = StringField("Título", validators=[DataRequired(), Length(max=255)])
    body = TextAreaField("Detalle", validators=[DataRequired(), Length(min=10)])
    submit = SubmitField("Abrir discusión")


class CommentForm(FlaskForm):
    content = TextAreaField("Comentario", validators=[DataRequired(), Length(min=5)])
    submit = SubmitField("Comentar")


class VoteForm(FlaskForm):
    value = HiddenField("Votar", validators=[DataRequired(), AnyOf(["1", "-1"])])
    submit = SubmitField("Votar")


class PostForm(FlaskForm):
    post_id = HiddenField()
    title = StringField("Título", validators=[DataRequired(), Length(max=255)])
    published_at = DateField("Fecha de publicación", format="%Y-%m-%d", validators=[Optional()])
    cover_image = StringField(
        "Imagen de portada (URL)",
        validators=[Optional(), URL(message="Introduce una URL válida"), Length(max=255)],
    )
    cover_image_file = FileField("Imagen original (subir archivo)", validators=[Optional()])
    image_layout = SelectField(
        "Maquetación de imagen",
        choices=[
            ("full", "Portada grande"),
            ("left", "Imagen a la izquierda"),
            ("right", "Imagen a la derecha"),
            ("bottom", "Imagen abajo"),
            ("none", "Sin imagen"),
        ],
        default="full",
    )
    category = SelectField(
        "Categoría",
        choices=[
            ("actividades", "Actividades"),
            ("comunicados", "Comunicados"),
            ("reuniones", "Reuniones"),
            ("general", "General"),
        ],
        default="general",
    )
    excerpt = TextAreaField("Resumen", validators=[Optional(), Length(max=512)])
    content = TextAreaField("Contenido", validators=[DataRequired()])
    status = SelectField(
        "Estado",
        choices=[("draft", "Borrador"), ("published", "Publicada")],
        default="draft",
    )
    submit = SubmitField("Publicar noticia")


class EventForm(FlaskForm):
    title = StringField("Título", validators=[DataRequired(), Length(max=255)])
    category = SelectField(
        "Categoría",
        choices=EVENT_CATEGORY_CHOICES,
        default="actividades",
        validators=[DataRequired()],
    )
    description = TextAreaField(
        "Descripción",
        validators=[DataRequired(), Length(min=10)],
        render_kw={"rows": 4},
    )
    start_at = StringField(
        "Inicio",
        validators=[DataRequired()],
        render_kw={"type": "datetime-local"},
    )
    end_at = StringField(
        "Fin",
        validators=[DataRequired()],
        render_kw={"type": "datetime-local"},
    )
    location = StringField("Ubicación", validators=[Optional(), Length(max=255)])
    capacity = IntegerField(
        "Aforo estimado",
        validators=[Optional()],
        default=None,
        render_kw={"min": "1"},
    )
    cover_image = StringField(
        "Imagen destacada (URL)",
        validators=[Optional(), URL(message="Introduce una URL válida"), Length(max=255)],
    )
    status = SelectField(
        "Estado",
        choices=[("draft", "Borrador"), ("published", "Publicada")],
        default="draft",
    )
    submit = SubmitField("Guardar evento")


class CommissionForm(FlaskForm):
    name = StringField("Nombre de la comision", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Descripcion y objetivos", validators=[Optional()])
    is_active = BooleanField("Comision activa", default=True)
    submit = SubmitField("Guardar comision")


class CommissionMemberForm(FlaskForm):
    user_id = SelectField("Seleccionar socio", coerce=int, validators=[DataRequired()])
    role = SelectField(
        "Rol en la comision",
        choices=[
            ("coordinador", "Coordinador"),
            ("miembro", "Miembro"),
        ],
        validators=[DataRequired()],
    )
    is_active = BooleanField("Activo", default=True)
    submit = SubmitField("Guardar miembro")


class CommissionProjectForm(FlaskForm):
    title = StringField("Titulo del proyecto", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Descripcion", validators=[Optional()])
    status = SelectField(
        "Estado",
        choices=[
            ("pendiente", "Pendiente"),
            ("en_progreso", "En progreso"),
            ("completado", "Completado"),
            ("en_pausa", "En pausa"),
        ],
        default="pendiente",
    )
    start_date = DateField("Fecha de inicio", format="%Y-%m-%d", validators=[Optional()])
    end_date = DateField("Fecha de fin", format="%Y-%m-%d", validators=[Optional()])
    responsible_id = SelectField("Responsable principal", coerce=int, validators=[Optional()])
    submit = SubmitField("Guardar proyecto")


class CommissionMeetingForm(FlaskForm):
    title = StringField("Titulo de la reunion", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Descripcion / agenda", validators=[Optional()])
    start_at = StringField(
        "Inicio",
        validators=[DataRequired()],
        render_kw={"type": "datetime-local"},
    )
    end_at = StringField(
        "Fin",
        validators=[DataRequired()],
        render_kw={"type": "datetime-local"},
    )
    location = StringField("Ubicacion", validators=[Optional(), Length(max=255)])
    minutes_document_id = SelectField(
        "Acta vinculada (opcional)", coerce=int, validators=[Optional()], choices=[]
    )
    submit = SubmitField("Guardar reunion")
