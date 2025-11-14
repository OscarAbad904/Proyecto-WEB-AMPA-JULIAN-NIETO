from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.fields import FileField
from wtforms.validators import DataRequired, Length


class SuggestionForm(FlaskForm):
    title = StringField("Título", validators=[DataRequired(), Length(max=255)])
    category = SelectField(
        "Categoría",
        choices=[("infraestructura", "Infraestructura"), ("actividades", "Actividades"), ("otro", "Otro")],
        validators=[DataRequired()],
    )
    body = TextAreaField("Detalle", validators=[DataRequired(), Length(min=10)])
    attachment = FileField("Adjuntar archivo (opcional)")
    submit = SubmitField("Enviar sugerencia")


class CommentForm(FlaskForm):
    content = TextAreaField("Comentario", validators=[DataRequired(), Length(min=5)])
    submit = SubmitField("Comentar")


class VoteForm(FlaskForm):
    value = SelectField("Votar", choices=[("1", "+1"), ("-1", "-1")], validators=[DataRequired()])
    submit = SubmitField("Votar")
