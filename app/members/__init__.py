import secrets
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db, login_manager
from ..forms import (
    CommentForm,
    LoginForm,
    NewMemberForm,
    RecoverForm,
    RegisterForm,
    ResetPasswordForm,
    SuggestionForm,
    VoteForm,
)
from ..models import Comment, Membership, Role, Suggestion, User, Vote
from ..utils.tokens import generate_confirmation_token

members_bp = Blueprint("members", __name__, template_folder="../../templates/members")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def _generate_password(length: int = 10) -> str:
    # token_urlsafe retorna base64, recortamos para legibilidad.
    return secrets.token_urlsafe(length)[:length]


def _generate_member_number(year: int) -> str:
    return f"{year}-SOC-{secrets.randbelow(9999):04}"


def _send_sms_code(phone: str, code: str) -> None:
    """Placeholder de envío SMS: log a consola para entorno dev."""
    print(f"[SMS] Enviar código {code} a {phone}")


@members_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("members.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash("Bienvenido de nuevo", "success")
            return redirect(url_for("members.dashboard"))
        flash("Credenciales inválidas", "danger")
    return render_template("members/login.html", form=form)


@members_bp.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash("Ya existe una cuenta con ese correo", "warning")
            return render_template("members/register.html", form=form)
        role = Role.query.filter_by(name="socio").first()
        if not role:
            role = Role(name="socio")
            db.session.add(role)
            db.session.commit()
        user = User(
            username=form.username.data,
            email=form.email.data.lower(),
            role=role,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        generate_confirmation_token(user.email)
        flash("Se ha enviado un correo de verificación", "info")
        return redirect(url_for("members.login"))
    return render_template("members/register.html", form=form)


@members_bp.route("/logout")
def logout():
    logout_user()
    flash("Sesión cerrada", "info")
    return redirect(url_for("public.home"))


@members_bp.route("/")
@login_required
def dashboard():
    alta_form = NewMemberForm()
    return render_template("members/dashboard.html", alta_form=alta_form)


@members_bp.route("/socios/alta", methods=["POST"])
@login_required
def alta_socio():
    if not current_user.is_admin:
        abort(403)
    form = NewMemberForm()
    if form.validate_on_submit():
        email = form.email.data.lower()
        if User.query.filter_by(email=email).first():
            flash("Ya existe un usuario con ese correo.", "warning")
            return redirect(url_for("members.dashboard"))
        role = Role.query.filter_by(name="socio").first()
        if not role:
            role = Role(name="socio")
            db.session.add(role)
            db.session.commit()
        username = email.split("@")[0]
        password = _generate_password()
        year = form.year.data or datetime.utcnow().year
        member_number = form.member_number.data or _generate_member_number(year)
        user = User(
            username=username,
            email=email,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            phone_number=form.phone_number.data,
            address=form.address.data,
            city=form.city.data,
            postal_code=form.postal_code.data,
            role=role,
            email_verified=True,
            two_fa_enabled=True,
        )
        user.set_password(password)
        membership = Membership(
            user=user,
            member_number=member_number,
            year=year,
            is_active=True,
        )
        db.session.add(user)
        db.session.add(membership)
        db.session.commit()
        flash(
            f"Socio creado. Usuario: {email} | Contraseña temporal: {password}",
            "success",
        )
    else:
        flash("Revisa los datos del formulario de alta.", "danger")
    return redirect(url_for("members.dashboard"))


@members_bp.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    email_form = RecoverForm()
    reset_form = ResetPasswordForm()
    reset_data = session.get("reset_flow")

    if email_form.validate_on_submit() and "stage" not in request.form:
        user = User.query.filter_by(email=email_form.email.data.lower()).first()
        if user and user.phone_number:
            code = f"{secrets.randbelow(1_000_000):06}"
            expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
            session["reset_flow"] = {
                "email": user.email,
                "code": code,
                "expires_at": expires_at,
            }
            _send_sms_code(user.phone_number, code)
            flash("Te hemos enviado un código SMS para restablecer la contraseña.", "info")
        else:
            flash("No hay teléfono asociado o la cuenta no existe.", "warning")
        return render_template("members/recuperar.html", email_form=email_form, reset_form=reset_form, stage="code")

    if reset_form.validate_on_submit() and request.form.get("stage") == "code":
        flow = reset_data or {}
        submitted_email = reset_form.email.data.lower()
        if not flow or flow.get("email") != submitted_email:
            flash("La solicitud de recuperación expiró o es inválida.", "danger")
            return render_template("members/recuperar.html", email_form=email_form, reset_form=reset_form, stage="code")
        if datetime.utcnow() > datetime.fromisoformat(flow["expires_at"]):
            session.pop("reset_flow", None)
            flash("El código ha expirado. Solicita uno nuevo.", "warning")
            return render_template("members/recuperar.html", email_form=email_form, reset_form=reset_form, stage="code")
        if reset_form.code.data != flow["code"]:
            flash("Código incorrecto.", "danger")
            return render_template("members/recuperar.html", email_form=email_form, reset_form=reset_form, stage="code")
        user = User.query.filter_by(email=submitted_email).first()
        if not user:
            flash("Cuenta no encontrada.", "danger")
            return render_template("members/recuperar.html", email_form=email_form, reset_form=reset_form, stage="code")
        user.set_password(reset_form.password.data)
        db.session.commit()
        session.pop("reset_flow", None)
        flash("Contraseña actualizada. Ya puedes iniciar sesión.", "success")
        return redirect(url_for("members.login"))

    return render_template(
        "members/recuperar.html",
        email_form=email_form,
        reset_form=reset_form,
        stage="code" if reset_data else "email",
    )


@members_bp.route("/sugerencias")
@login_required
def sugerencias():
    status = request.args.get("status", "pendiente")
    page = request.args.get("page", 1, type=int)
    suggestions = (
        Suggestion.query.filter_by(status=status)
        .order_by(Suggestion.votes_count.desc())
        .paginate(page=page, per_page=5)
    )
    return render_template("members/sugerencias.html", suggestions=suggestions, status=status)


@members_bp.route("/sugerencias/nueva", methods=["GET", "POST"])
@login_required
def nueva_sugerencia():
    form = SuggestionForm()
    if form.validate_on_submit():
        suggestion = Suggestion(
            title=form.title.data,
            body_html=form.body.data,
            category=form.category.data,
            created_by=current_user.id,
        )
        db.session.add(suggestion)
        db.session.commit()
        flash("Sugerencia creada", "success")
        return redirect(url_for("members.sugerencias"))
    return render_template("members/sugerencia_form.html", form=form)


@members_bp.route("/sugerencias/<int:suggestion_id>")
@login_required
def detalle_sugerencia(suggestion_id):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    comment_form = CommentForm()
    vote_form = VoteForm()
    return render_template(
        "members/sugerencia_detalle.html",
        suggestion=suggestion,
        comment_form=comment_form,
        vote_form=vote_form,
    )


@members_bp.route("/sugerencias/<int:suggestion_id>/comentar", methods=["POST"])
@login_required
def comentar_sugerencia(suggestion_id):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    form = CommentForm()
    if form.validate_on_submit():
        parent_id = request.form.get("parent_id")
        comment = Comment(
            suggestion_id=suggestion.id,
            body_html=form.content.data,
            created_by=current_user.id,
            parent_id=parent_id,
        )
        db.session.add(comment)
        db.session.commit()
        flash("Comentario añadido", "success")
    return redirect(url_for("members.detalle_sugerencia", suggestion_id=suggestion_id))


@members_bp.route("/sugerencias/<int:suggestion_id>/votar", methods=["POST"])
@login_required
def votar_sugerencia(suggestion_id):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    form = VoteForm()
    if form.validate_on_submit():
        value = int(form.value.data)
        vote = Vote.query.filter_by(user_id=current_user.id, suggestion_id=suggestion.id).first()
        if vote:
            suggestion.votes_count -= vote.value
            vote.value = value
        else:
            vote = Vote(suggestion_id=suggestion.id, user_id=current_user.id, value=value)
            db.session.add(vote)
        suggestion.votes_count += value
        db.session.commit()
        flash("Voto registrado", "success")
    return redirect(url_for("members.detalle_sugerencia", suggestion_id=suggestion_id))
