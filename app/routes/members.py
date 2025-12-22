from flask import Blueprint, render_template, request, flash, redirect, url_for, session, abort, jsonify, current_app
from flask_login import login_required, current_user, login_user, logout_user
from datetime import datetime, timedelta
import secrets
import re
from urllib.parse import urlparse
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import (
    User,
    Role,
    Permission,
    Membership,
    Suggestion,
    Comment,
    Vote,
    Document,
    Commission,
    CommissionMembership,
    CommissionProject,
    CommissionMeeting,
    user_is_privileged,
)
from app.forms import (
    LoginForm,
    RegisterForm,
    NewMemberForm,
    RecoverForm,
    ResetPasswordForm,
    UpdatePhoneForm,
    ChangePasswordForm,
    SuggestionForm,
    CommissionDiscussionForm,
    CommentForm,
    VoteForm,
    CommissionMemberForm,
    CommissionProjectForm,
    CommissionMeetingForm,
)
from app.utils import (
    make_lookup_hash,
    normalize_lookup,
    generate_email_verification_token,
    _generate_password,
    _generate_member_number,
    _send_sms_code,
    _parse_datetime_local,
)
from app.services.permission_registry import ensure_roles_and_permissions, DEFAULT_ROLE_NAMES

members_bp = Blueprint("members", __name__, template_folder="../../templates/members")


def _get_commission_and_membership(slug: str):
    commission = Commission.query.filter_by(slug=slug).first_or_404()
    membership = CommissionMembership.query.filter_by(
        commission_id=commission.id, user_id=current_user.id, is_active=True
    ).first()
    return commission, membership


def _commission_discussion_commission_id(raw_category: str | None) -> int | None:
    category = (raw_category or "").strip()
    if not category.startswith("comision:"):
        return None
    raw_id = category.split(":", 1)[1].strip()
    try:
        return int(raw_id)
    except ValueError:
        return None


def _project_discussion_project_id(raw_category: str | None) -> int | None:
    category = (raw_category or "").strip()
    if not category.startswith("proyecto:"):
        return None
    raw_id = category.split(":", 1)[1].strip()
    try:
        return int(raw_id)
    except ValueError:
        return None


def _safe_return_to(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    value = raw_value.strip()
    if not value.startswith("/"):
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return None
    return value


def _discussion_back_target(suggestion: Suggestion, return_to: str | None = None):
    """Devuelve (back_url, back_label, breadcrumb) para el detalle de una discusión."""
    category = (getattr(suggestion, "category", None) or "").strip()

    commission_id = _commission_discussion_commission_id(category)
    if commission_id is not None:
        commission = Commission.query.get(commission_id)
        if commission and commission.slug:
            if return_to:
                return (
                    return_to,
                    "Volver a la comisión",
                    f"Administración · Comisión · {commission.name} · Discusiones · {suggestion.title}",
                )
            return (
                url_for("members.commission_detail", slug=commission.slug),
                "Volver a la comisión",
                f"Área privada · Comisión · {commission.name} · Discusiones · {suggestion.title}",
            )

    project_id = _project_discussion_project_id(category)
    if project_id is not None:
        project = CommissionProject.query.get(project_id)
        if project:
            commission = Commission.query.get(getattr(project, "commission_id", None))
            if commission and commission.slug:
                if return_to:
                    return (
                        return_to,
                        "Volver al proyecto",
                        f"Administración · Proyecto · {project.title} · Discusiones · {suggestion.title}",
                    )
                return (
                    url_for("members.commission_project_detail", slug=commission.slug, project_id=project.id),
                    "Volver al proyecto",
                    f"Área privada · Proyecto · {project.title} · Discusiones · {suggestion.title}",
                )

    return (
        url_for("members.sugerencias"),
        "Volver a sugerencias",
        f"Área privada · Foro de sugerencias · {suggestion.title}",
    )


def _ensure_can_access_commission_discussion(suggestion: Suggestion) -> None:
    commission_id = _commission_discussion_commission_id(getattr(suggestion, "category", None))
    if commission_id is None:
        return

    membership = CommissionMembership.query.filter_by(
        commission_id=commission_id, user_id=current_user.id, is_active=True
    ).first()
    can_view_commission = (
        bool(membership)
        or current_user.has_permission("view_commissions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commission:
        abort(403)


def _ensure_can_access_project_discussion(suggestion: Suggestion) -> None:
    project_id = _project_discussion_project_id(getattr(suggestion, "category", None))
    if project_id is None:
        return

    project = CommissionProject.query.get(project_id)
    if not project:
        abort(404)

    membership = CommissionMembership.query.filter_by(
        commission_id=project.commission_id, user_id=current_user.id, is_active=True
    ).first()
    can_view_commission = (
        bool(membership)
        or current_user.has_permission("view_commissions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commission:
        abort(403)


def _ensure_can_access_scoped_discussion(suggestion: Suggestion) -> None:
    _ensure_can_access_commission_discussion(suggestion)
    _ensure_can_access_project_discussion(suggestion)


def _user_is_commission_coordinator(membership: CommissionMembership | None) -> bool:
    return bool(membership and membership.role == "coordinador")

def _commission_can_manage(membership: CommissionMembership | None, area: str) -> bool:
    if not membership or not membership.is_active:
        return False
    role = (membership.role or "").strip().lower()
    if role == "coordinador":
        return area in {"members", "projects", "meetings"}
    return False


@members_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("public.home"))
    form = LoginForm()
    if form.validate_on_submit():
        lookup_email = make_lookup_hash(form.email.data)
        user = User.query.filter_by(email_lookup=lookup_email).first()
        if user and user.check_password(form.password.data):
            if getattr(user, "deleted_at", None):
                flash("Tu cuenta ha sido eliminada.", "danger")
                return render_template("members/login.html", form=form)
            if not user.is_active:
                flash("Tu cuenta está desactivada.", "danger")
                return render_template("members/login.html", form=form)
            if not user.email_verified:
                flash("Debes verificar tu correo antes de iniciar sesión.", "warning")
                return render_template("members/login.html", form=form)

            login_user(user, remember=form.remember_me.data)
            user.last_login = datetime.utcnow()
            db.session.commit()

            if not user.registration_approved:
                flash("Tu alta está pendiente de aprobación. Solo puedes acceder a tu perfil.", "info")
                return redirect(url_for("public.home"))

            flash("Bienvenido de nuevo", "success")
            return redirect(url_for("public.home"))
        flash("Credenciales inválidas", "danger")
    return render_template("members/login.html", form=form)


@members_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        if request.is_json:
            return jsonify({"ok": False, "message": "Ya has iniciado sesión."}), 400
        return redirect(url_for("public.home"))

    if Permission.supports_public_flag():
        try:
            is_public = db.session.query(Permission.is_public).filter_by(key="public_registration").scalar()
            if is_public is False:
                if request.is_json:
                    return jsonify({"ok": False, "message": "El registro de socios está cerrado temporalmente."}), 403
                flash("El registro de socios está cerrado temporalmente.", "info")
                return redirect(url_for("public.home"))
        except Exception:
            pass

    form = RegisterForm()

    # Manejo de solicitud AJAX (JSON o XMLHttpRequest)
    if (request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest") and request.method == "POST":
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form

        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        phone_number = (data.get("phone_number") or "").strip()
        privacy_accepted = data.get("privacy_accepted")

        if not all([first_name, last_name, email, privacy_accepted]):
            return jsonify({"ok": False, "message": "Faltan campos obligatorios o no se ha aceptado la política de privacidad."}), 400

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({"ok": False, "message": "El formato del email no es válido."}), 400

        from app.services.mail_service import (
            send_member_verification_email,
            send_new_member_registration_notification_to_ampa,
        )

        lookup_email = make_lookup_hash(email)
        existing_user = User.query.filter_by(email_lookup=lookup_email).first()

        if existing_user:
            if existing_user.is_active and not existing_user.email_verified:
                token = generate_email_verification_token(existing_user.id, existing_user.email_lookup)
                verify_url = url_for("public.verify_email", token=token, _external=True)
                send_member_verification_email(
                    recipient_email=existing_user.email,
                    verify_url=verify_url,
                    app_config=current_app.config,
                )
            return jsonify({
                "ok": True,
                "message": "Si el correo es válido, recibirás un enlace de verificación. Revisa tu bandeja de entrada."
            })

        ensure_roles_and_permissions(DEFAULT_ROLE_NAMES)
        role = Role.query.filter_by(name_lookup=normalize_lookup("socio")).first()
        if not role:
            role = Role(name="Socio")
            db.session.add(role)
            db.session.commit()

        user = User(
            username=email,
            email=email,
            role=role,
            first_name=first_name,
            last_name=last_name,
            phone_number=phone_number or None,
            email_verified=False,
            registration_approved=False,
            privacy_accepted_at=datetime.utcnow(),
            privacy_version=str(data.get("privacy_version", current_app.config.get("PRIVACY_POLICY_VERSION", "1"))),
        )
        user.set_password(secrets.token_urlsafe(32))
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({
                "ok": True,
                "message": "Si el correo es válido, recibirás un enlace de verificación. Revisa tu bandeja de entrada."
            })

        token = generate_email_verification_token(user.id, user.email_lookup)
        verify_url = url_for("public.verify_email", token=token, _external=True)
        verification_result = send_member_verification_email(
            recipient_email=user.email,
            verify_url=verify_url,
            app_config=current_app.config,
        )

        full_name = f"{user.first_name} {user.last_name}".strip()
        send_new_member_registration_notification_to_ampa(
            member_name=full_name or "Socio",
            member_email=user.email,
            member_phone=user.phone_number,
            app_config=current_app.config,
        )

        if verification_result.get("ok"):
            return jsonify({"ok": True, "message": "Registro recibido. Hemos enviado un enlace de verificación a tu correo. Revisa tu bandeja de entrada."})
        else:
            return jsonify({"ok": True, "message": "Registro recibido, pero hubo un problema enviando el email de verificación. Contacta con el AMPA."})

    # Fallback para GET o POST tradicional (aunque el JS ahora usa AJAX)
    if form.validate_on_submit():
        from app.services.mail_service import (
            send_member_verification_email,
            send_new_member_registration_notification_to_ampa,
        )

        email = (form.email.data or "").strip().lower()
        lookup_email = make_lookup_hash(email)
        existing_user = User.query.filter_by(email_lookup=lookup_email).first()

        if existing_user:
            if existing_user.is_active and not existing_user.email_verified:
                token = generate_email_verification_token(existing_user.id, existing_user.email_lookup)
                verify_url = url_for("public.verify_email", token=token, _external=True)
                send_member_verification_email(
                    recipient_email=existing_user.email,
                    verify_url=verify_url,
                    app_config=current_app.config,
                )
            flash(
                "Si el correo es valido, recibiras un enlace de verificacion. "
                "Revisa tu bandeja de entrada y, si no aparece, el correo no deseado o spam.",
                "info",
            )
            return redirect(url_for("members.login"))

        ensure_roles_and_permissions(DEFAULT_ROLE_NAMES)
        role = Role.query.filter_by(name_lookup=normalize_lookup("socio")).first()
        if not role:
            role = Role(name="Socio")
            db.session.add(role)
            db.session.commit()

        user = User(
            username=email,
            email=email,
            role=role,
            first_name=form.first_name.data,
            last_name=form.last_name.data,
            phone_number=(form.phone_number.data or "").strip() or None,
            email_verified=False,
            registration_approved=False,
            privacy_accepted_at=datetime.utcnow(),
            privacy_version=str(current_app.config.get("PRIVACY_POLICY_VERSION", "1")),
        )
        user.set_password(secrets.token_urlsafe(32))
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash(
                "Si el correo es valido, recibiras un enlace de verificacion.",
                "info",
            )
            return redirect(url_for("members.login"))

        token = generate_email_verification_token(user.id, user.email_lookup)
        verify_url = url_for("public.verify_email", token=token, _external=True)
        verification_result = send_member_verification_email(
            recipient_email=user.email,
            verify_url=verify_url,
            app_config=current_app.config,
        )

        full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
        send_new_member_registration_notification_to_ampa(
            member_name=full_name or "Socio",
            member_email=user.email,
            member_phone=user.phone_number,
            app_config=current_app.config,
        )

        if verification_result.get("ok"):
            flash(
                "Registro recibido. Hemos enviado un enlace de verificacion a tu correo.",
                "success",
            )
        else:
            flash(
                "Registro recibido, pero no se pudo enviar el enlace de verificación.",
                "danger",
            )
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


@members_bp.route("/mi-cuenta", methods=["GET", "POST"])
@login_required
def mi_cuenta():
    phone_form = UpdatePhoneForm()
    password_form = ChangePasswordForm()

    if request.method == "GET":
        phone_form.phone_number.data = current_user.phone_number or ""

    if phone_form.submit_phone.data and phone_form.validate_on_submit():
        current_user.phone_number = (phone_form.phone_number.data or "").strip() or None
        db.session.commit()
        flash("Teléfono actualizado.", "success")
        return redirect(url_for("public.home"))

    if password_form.submit_password.data and password_form.validate_on_submit():
        if not current_user.check_password(password_form.current_password.data):
            flash("Contraseña actual incorrecta.", "danger")
            return redirect(url_for("public.home"))
        current_user.set_password(password_form.new_password.data)
        db.session.commit()
        flash("Contraseña actualizada.", "success")
        return redirect(url_for("public.home"))

    return render_template(
        "members/mi_cuenta.html",
        phone_form=phone_form,
        password_form=password_form,
    )


@members_bp.route("/socios/alta", methods=["POST"])
@login_required
def alta_socio():
    if not (current_user.has_permission("manage_members") or user_is_privileged(current_user)):
        abort(403)
    form = NewMemberForm()
    if form.validate_on_submit():
        email = form.email.data
        lookup_email = make_lookup_hash(email)
        if User.query.filter_by(email_lookup=lookup_email).first():
            flash("Ya existe un usuario con ese correo.", "warning")
            return redirect(url_for("members.dashboard"))
        role = Role.query.filter_by(name_lookup=normalize_lookup("socio")).first()
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
            registration_approved=True,
            approved_at=datetime.utcnow(),
            approved_by_id=current_user.id,
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
        lookup_email = make_lookup_hash(email_form.email.data)
        user = User.query.filter_by(email_lookup=lookup_email).first()
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
        return render_template(
            "members/recuperar.html",
            email_form=email_form,
            reset_form=reset_form,
            stage="code",
        )

    if reset_form.validate_on_submit() and request.form.get("stage") == "code":
        flow = reset_data or {}
        submitted_email = reset_form.email.data
        if not flow or flow.get("email") != submitted_email:
            flash("La solicitud de recuperación expiró o es inválida.", "danger")
            return render_template(
                "members/recuperar.html",
                email_form=email_form,
                reset_form=reset_form,
                stage="code",
            )
        if datetime.utcnow() > datetime.fromisoformat(flow["expires_at"]):
            session.pop("reset_flow", None)
            flash("El código ha expirado. Solicita uno nuevo.", "warning")
            return render_template(
                "members/recuperar.html",
                email_form=email_form,
                reset_form=reset_form,
                stage="code",
            )
        if reset_form.code.data != flow["code"]:
            flash("Código incorrecto.", "danger")
            return render_template(
                "members/recuperar.html",
                email_form=email_form,
                reset_form=reset_form,
                stage="code",
            )
        user = User.query.filter_by(email_lookup=make_lookup_hash(submitted_email)).first()
        if not user:
            flash("Cuenta no encontrada.", "danger")
            return render_template(
                "members/recuperar.html",
                email_form=email_form,
                reset_form=reset_form,
                stage="code",
            )
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
    if not current_user.has_permission("view_suggestions"):
        abort(403)
    status = request.args.get("status", "pendiente")
    page = request.args.get("page", 1, type=int)
    suggestions = (
        Suggestion.query.filter_by(status=status)
        .filter(
            ~Suggestion.category.like("comision:%"),
            ~Suggestion.category.like("proyecto:%"),
        )
        .order_by(Suggestion.votes_count.desc())
        .paginate(page=page, per_page=5)
    )
    return render_template("members/sugerencias.html", suggestions=suggestions, status=status)


@members_bp.route("/comisiones/<slug>/discusiones/nueva", methods=["GET", "POST"])
@login_required
def commission_discussion_new(slug: str):
    commission, membership = _get_commission_and_membership(slug)
    can_view_commission = (
        bool(membership)
        or current_user.has_permission("view_commissions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commission:
        abort(403)
    if not current_user.has_permission("create_suggestions"):
        abort(403)

    return_to = _safe_return_to(request.args.get("return_to"))

    form = CommissionDiscussionForm()
    if form.validate_on_submit():
        suggestion = Suggestion(
            title=form.title.data,
            body_html=form.body.data,
            category=f"comision:{commission.id}",
            created_by=current_user.id,
        )
        db.session.add(suggestion)
        db.session.commit()
        flash("Discusión creada", "success")
        return redirect(
            url_for(
                "members.detalle_sugerencia",
                suggestion_id=suggestion.id,
                return_to=return_to,
            )
            if return_to
            else url_for("members.detalle_sugerencia", suggestion_id=suggestion.id)
        )

    return render_template(
        "members/comision_discusion_form.html",
        form=form,
        commission=commission,
        return_to=return_to,
    )


@members_bp.route("/sugerencias/nueva", methods=["GET", "POST"])
@login_required
def nueva_sugerencia():
    if not current_user.has_permission("create_suggestions"):
        abort(403)
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
def detalle_sugerencia(suggestion_id: int):
    if not current_user.has_permission("view_suggestions"):
        abort(403)
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    _ensure_can_access_scoped_discussion(suggestion)
    return_to = _safe_return_to(request.args.get("return_to"))
    back_url, back_label, breadcrumb = _discussion_back_target(suggestion, return_to=return_to)
    comment_form = CommentForm()
    vote_form = VoteForm()
    user_vote = suggestion.votes.filter_by(user_id=current_user.id).first()
    if user_vote:
        vote_form.value.data = str(user_vote.value)
    comments = suggestion.comments.order_by(Comment.created_at.asc()).all()
    likes_count = suggestion.votes.filter_by(value=1).count()
    dislikes_count = suggestion.votes.filter_by(value=-1).count()
    is_closed = suggestion.status == "cerrada"
    return render_template(
        "members/sugerencia_detalle.html",
        suggestion=suggestion,
        comments=comments,
        Comment=Comment,
        comment_form=comment_form,
        vote_form=vote_form,
        user_vote=user_vote,
        likes_count=likes_count,
        dislikes_count=dislikes_count,
        is_closed=is_closed,
        back_url=back_url,
        back_label=back_label,
        breadcrumb=breadcrumb,
    )


@members_bp.route("/sugerencias/<int:suggestion_id>/comentar", methods=["POST"])
@login_required
def comentar_sugerencia(suggestion_id: int):
    if not current_user.has_permission("comment_suggestions"):
        abort(403)
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    _ensure_can_access_scoped_discussion(suggestion)
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


@members_bp.route("/comentarios/<int:comment_id>/editar", methods=["POST"])
@login_required
def editar_comentario(comment_id: int):
    comment = Comment.query.get_or_404(comment_id)
    if comment.created_by != current_user.id:
        abort(403)

    # Verificar si es el último mensaje del hilo (nadie ha escrito después en esa sugerencia)
    last_comment = Comment.query.filter_by(suggestion_id=comment.suggestion_id).order_by(Comment.created_at.desc()).first()
    if last_comment.id != comment.id:
        flash("Solo puedes editar tu último mensaje si no hay respuestas posteriores.", "warning")
        return redirect(url_for("members.detalle_sugerencia", suggestion_id=comment.suggestion_id))

    form = CommentForm()
    if form.validate_on_submit():
        comment.body_html = form.content.data
        comment.is_edited = True
        comment.created_at = datetime.utcnow()
        db.session.commit()
        flash("Comentario actualizado", "success")
    return redirect(url_for("members.detalle_sugerencia", suggestion_id=comment.suggestion_id))


@members_bp.route("/sugerencias/<int:suggestion_id>/votar", methods=["POST"])
@login_required
def votar_sugerencia(suggestion_id: int):
    if not current_user.has_permission("vote_suggestions"):
        abort(403)
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    _ensure_can_access_scoped_discussion(suggestion)
    if suggestion.status == "cerrada":
        message = "El hilo está cerrado; no se pueden registrar votos nuevos."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(success=False, message=message), 400
        flash(message, "warning")
        return redirect(url_for("members.detalle_sugerencia", suggestion_id=suggestion_id))
    form = VoteForm()
    if form.validate_on_submit():
        try:
            value = int(form.value.data)
        except (TypeError, ValueError):
            message = "El valor del voto no es válido."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(success=False, message=message), 400
            flash(message, "danger")
            return redirect(url_for("members.detalle_sugerencia", suggestion_id=suggestion_id))
        if value not in (-1, 1):
            message = "El valor del voto no es válido."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(success=False, message=message), 400
            flash(message, "danger")
            return redirect(url_for("members.detalle_sugerencia", suggestion_id=suggestion_id))
        vote = Vote.query.filter_by(user_id=current_user.id, suggestion_id=suggestion.id).first()
        if vote and vote.value == value:
            message = "Tu voto ya está registrado con esa opción."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify(success=False, message=message), 200
            flash(message, "info")
            return redirect(url_for("members.detalle_sugerencia", suggestion_id=suggestion_id))

        previous_value = vote.value if vote else 0
        if vote:
            vote.value = value
        else:
            vote = Vote(suggestion_id=suggestion.id, user_id=current_user.id, value=value)
            db.session.add(vote)
        suggestion.votes_count = (suggestion.votes_count or 0) - previous_value + value
        db.session.commit()
        likes_count = suggestion.votes.filter_by(value=1).count()
        dislikes_count = suggestion.votes.filter_by(value=-1).count()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(
                success=True,
                message="Voto actualizado" if previous_value else "Voto registrado",
                vote=value,
                likes=likes_count,
                dislikes=dislikes_count,
            )
        flash("Voto actualizado" if previous_value else "Voto registrado", "success")
    else:
        message = "Selecciona Me gusta o No me gusta antes de guardar."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(success=False, message=message), 400
        flash(message, "warning")
    return redirect(url_for("members.detalle_sugerencia", suggestion_id=suggestion_id))


@members_bp.route("/comisiones")
@login_required
def commissions():
    scope = request.args.get("scope", "mis")
    can_view_all = current_user.has_permission("view_commissions")
    member_memberships = (
        CommissionMembership.query.filter_by(user_id=current_user.id, is_active=True)
        .join(Commission)
        .filter(Commission.is_active.is_(True))
        .all()
    )
    memberships_map = {m.commission_id: m for m in member_memberships}

    if not can_view_all and not memberships_map:
        abort(403)

    if scope == "todas" and not can_view_all:
        scope = "mis"

    query = Commission.query.filter_by(is_active=True)
    if scope != "todas" or not can_view_all:
        commission_ids = list(memberships_map.keys())
        query = query.filter(Commission.id.in_(commission_ids)) if commission_ids else query.filter(Commission.id == -1)

    commissions = query.order_by(Commission.name.asc()).all()

    return render_template(
        "members/comisiones.html",
        commissions=commissions,
        memberships=memberships_map,
        scope=scope,
        can_view_all=can_view_all,
    )


@members_bp.route("/comisiones/<slug>")
@login_required
def commission_detail(slug: str):
    commission, membership = _get_commission_and_membership(slug)
    can_view_commission = bool(membership) or current_user.has_permission("view_commissions") or user_is_privileged(current_user)
    if not can_view_commission:
        abort(403)

    members = (
        commission.memberships.join(User)
        .filter(
            CommissionMembership.is_active.is_(True),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
        .order_by(CommissionMembership.role.asc())
        .all()
    )
    projects = commission.projects.order_by(CommissionProject.created_at.desc()).all()

    commission_discussions = (
        Suggestion.query.filter(
            Suggestion.category == f"comision:{commission.id}",
            Suggestion.status.in_(("pendiente", "aprobada")),
        )
        .order_by(Suggestion.updated_at.desc())
        .limit(20)
        .all()
    )
    now_dt = datetime.utcnow()
    upcoming_meetings = (
        commission.meetings.filter(CommissionMeeting.end_at >= now_dt)
        .order_by(CommissionMeeting.start_at.asc())
        .all()
    )
    past_meetings = (
        commission.meetings.filter(CommissionMeeting.end_at < now_dt)
        .order_by(CommissionMeeting.start_at.desc())
        .all()
    )

    is_coordinator = bool(membership and membership.role == "coordinador")
    can_manage_members = _commission_can_manage(membership, "members") or current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    can_manage_projects = _commission_can_manage(membership, "projects") or current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    can_manage_meetings = _commission_can_manage(membership, "meetings") or current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    can_edit_commission = current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    can_create_discussions = current_user.has_permission("create_suggestions")

    return render_template(
        "members/comision_detalle.html",
        commission=commission,
        membership=membership,
        members=members,
        projects=projects,
        commission_discussions=commission_discussions,
        upcoming_meetings=upcoming_meetings,
        past_meetings=past_meetings,
        is_coordinator=is_coordinator,
        can_manage_members=can_manage_members,
        can_manage_projects=can_manage_projects,
        can_manage_meetings=can_manage_meetings,
        can_edit_commission=can_edit_commission,
        can_create_discussions=can_create_discussions,
    )


@members_bp.route("/comisiones/<slug>/proyectos/<int:project_id>")
@login_required
def commission_project_detail(slug: str, project_id: int):
    commission, membership = _get_commission_and_membership(slug)
    return_to = _safe_return_to(request.args.get("return_to"))
    can_view_commission = (
        bool(membership)
        or current_user.has_permission("view_commissions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commission:
        abort(403)

    project = CommissionProject.query.filter_by(id=project_id, commission_id=commission.id).first_or_404()

    project_discussions = (
        Suggestion.query.filter(
            Suggestion.category == f"proyecto:{project.id}",
            Suggestion.status.in_(("pendiente", "aprobada")),
        )
        .order_by(Suggestion.updated_at.desc())
        .limit(20)
        .all()
    )

    can_create_discussions = current_user.has_permission("create_suggestions")
    can_manage_projects = (
        _commission_can_manage(membership, "projects")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )

    if return_to:
        back_url = return_to
        back_label = "Volver al panel"
    else:
        back_url = url_for("members.commission_detail", slug=commission.slug)
        back_label = "Volver a la comisión"

    project_self_url = url_for(
        "members.commission_project_detail",
        slug=commission.slug,
        project_id=project.id,
        return_to=return_to,
    )

    return render_template(
        "members/comision_proyecto_detalle.html",
        commission=commission,
        project=project,
        membership=membership,
        project_discussions=project_discussions,
        can_create_discussions=can_create_discussions,
        can_manage_projects=can_manage_projects,
        return_to=return_to,
        back_url=back_url,
        back_label=back_label,
        project_self_url=project_self_url,
    )


@members_bp.route(
    "/comisiones/<slug>/proyectos/<int:project_id>/discusiones/nueva",
    methods=["GET", "POST"],
)
@login_required
def project_discussion_new(slug: str, project_id: int):
    commission, membership = _get_commission_and_membership(slug)
    return_to = _safe_return_to(request.args.get("return_to"))
    can_view_commission = (
        bool(membership)
        or current_user.has_permission("view_commissions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commission:
        abort(403)
    if not current_user.has_permission("create_suggestions"):
        abort(403)

    project = CommissionProject.query.filter_by(id=project_id, commission_id=commission.id).first_or_404()

    project_self_url = url_for(
        "members.commission_project_detail",
        slug=commission.slug,
        project_id=project.id,
        return_to=return_to,
    )

    form = CommissionDiscussionForm()
    if form.validate_on_submit():
        suggestion = Suggestion(
            title=form.title.data,
            body_html=form.body.data,
            category=f"proyecto:{project.id}",
            created_by=current_user.id,
        )
        db.session.add(suggestion)
        db.session.commit()
        flash("Discusión creada", "success")
        return redirect(
            url_for(
                "members.detalle_sugerencia",
                suggestion_id=suggestion.id,
                return_to=project_self_url,
            )
        )

    return render_template(
        "members/proyecto_discusion_form.html",
        form=form,
        commission=commission,
        project=project,
        return_to=return_to,
        back_url=project_self_url,
    )


@members_bp.route("/comisiones/<slug>/miembros/nuevo", methods=["GET", "POST"])
@login_required
def commission_member_new(slug: str):
    commission, membership = _get_commission_and_membership(slug)
    is_coord = _user_is_commission_coordinator(membership)
    if not (is_coord or current_user.has_permission("manage_commissions") or user_is_privileged(current_user)):
        abort(403)

    form = CommissionMemberForm()
    active_users = (
        User.query.filter_by(is_active=True, registration_approved=True)
        .filter(User.deleted_at.is_(None))
        .all()
    )
    active_users_sorted = sorted(active_users, key=lambda user: user.display_name.casefold())
    form.user_id.choices = [(user.id, user.display_name) for user in active_users_sorted]

    if form.validate_on_submit():
        existing = CommissionMembership.query.filter_by(
            commission_id=commission.id, user_id=form.user_id.data
        ).first()
        if existing:
            existing.role = form.role.data
            existing.is_active = form.is_active.data
        else:
            membership_obj = CommissionMembership(
                commission_id=commission.id,
                user_id=form.user_id.data,
                role=form.role.data,
                is_active=form.is_active.data,
            )
            db.session.add(membership_obj)
        db.session.commit()
        flash("Miembro guardado en la comisión", "success")
        return redirect(url_for("members.commission_detail", slug=slug))

    return render_template("members/comision_miembro_form.html", form=form, commission=commission)


@members_bp.route("/comisiones/<slug>/miembros/<int:membership_id>/desactivar", methods=["POST"])
@login_required
def commission_member_disable(slug: str, membership_id: int):
    commission, membership = _get_commission_and_membership(slug)
    is_coord = _user_is_commission_coordinator(membership)
    if not (is_coord or current_user.has_permission("manage_commissions") or user_is_privileged(current_user)):
        abort(403)

    target = CommissionMembership.query.filter_by(id=membership_id, commission_id=commission.id).first_or_404()
    target.is_active = False
    db.session.commit()
    flash("Miembro desactivado", "info")
    return redirect(url_for("members.commission_detail", slug=slug))


@members_bp.route("/comisiones/<slug>/proyectos/nuevo", methods=["GET", "POST"])
@members_bp.route("/comisiones/<slug>/proyectos/<int:project_id>/editar", methods=["GET", "POST"])
@login_required
def commission_project_form(slug: str, project_id: int | None = None):
    commission, membership = _get_commission_and_membership(slug)
    is_coord = _user_is_commission_coordinator(membership)
    if not (is_coord or current_user.has_permission("manage_commissions") or user_is_privileged(current_user)):
        abort(403)

    project = CommissionProject.query.filter_by(id=project_id, commission_id=commission.id).first() if project_id else None
    form = CommissionProjectForm(obj=project)
    active_users = (
        User.query.filter_by(is_active=True, registration_approved=True)
        .filter(User.deleted_at.is_(None))
        .all()
    )
    active_users_sorted = sorted(active_users, key=lambda user: user.display_name.casefold())
    user_choices = [(user.id, user.display_name) for user in active_users_sorted]
    form.responsible_id.choices = [(0, "Sin responsable")] + user_choices

    if form.validate_on_submit():
        responsible_id = form.responsible_id.data or None
        if responsible_id == 0:
            responsible_id = None
        if project:
            project.title = form.title.data
            project.description_html = form.description.data
            project.status = form.status.data
            project.start_date = form.start_date.data
            project.end_date = form.end_date.data
            project.responsible_id = responsible_id
        else:
            project = CommissionProject(
                commission_id=commission.id,
                title=form.title.data,
                description_html=form.description.data,
                status=form.status.data,
                start_date=form.start_date.data,
                end_date=form.end_date.data,
                responsible_id=responsible_id,
            )
            db.session.add(project)
        db.session.commit()
        flash("Proyecto guardado", "success")
        return redirect(url_for("members.commission_detail", slug=slug))

    if request.method == "GET" and project:
        form.responsible_id.data = project.responsible_id or 0

    return render_template(
        "members/comision_proyecto_form.html",
        form=form,
        commission=commission,
        project=project,
    )


@members_bp.route("/comisiones/<slug>/reuniones/nueva", methods=["GET", "POST"])
@members_bp.route("/comisiones/<slug>/reuniones/<int:meeting_id>/editar", methods=["GET", "POST"])
@login_required
def commission_meeting_form(slug: str, meeting_id: int | None = None):
    commission, membership = _get_commission_and_membership(slug)
    is_coord = _user_is_commission_coordinator(membership)
    if not (is_coord or current_user.has_permission("manage_commissions") or user_is_privileged(current_user)):
        abort(403)

    meeting = CommissionMeeting.query.filter_by(id=meeting_id, commission_id=commission.id).first() if meeting_id else None
    form = CommissionMeetingForm(obj=meeting)
    document_choices = [(0, "Sin acta")] + [
        (doc.id, doc.title or f"Documento {doc.id}") for doc in Document.query.order_by(Document.created_at.desc()).all()
    ]
    form.minutes_document_id.choices = document_choices

    if form.validate_on_submit():
        start_at = _parse_datetime_local(form.start_at.data)
        end_at = _parse_datetime_local(form.end_at.data)
        if not start_at or not end_at or end_at <= start_at:
            flash("Fechas de inicio y fin deben ser válidas y fin posterior a inicio.", "warning")
            return render_template(
                "members/comision_reunion_form.html",
                form=form,
                commission=commission,
                meeting=meeting,
            )
        minutes_document_id = form.minutes_document_id.data or None
        if minutes_document_id == 0:
            minutes_document_id = None

        if meeting:
            meeting.title = form.title.data
            meeting.description_html = form.description.data
            meeting.start_at = start_at
            meeting.end_at = end_at
            meeting.location = form.location.data
            meeting.minutes_document_id = minutes_document_id
        else:
            meeting = CommissionMeeting(
                commission_id=commission.id,
                title=form.title.data,
                description_html=form.description.data,
                start_at=start_at,
                end_at=end_at,
                location=form.location.data,
                minutes_document_id=minutes_document_id,
            )
            db.session.add(meeting)
        db.session.commit()
        flash("Reunión guardada", "success")
        return redirect(url_for("members.commission_detail", slug=slug))

    if request.method == "GET" and meeting:
        form.minutes_document_id.data = meeting.minutes_document_id or 0
        form.start_at.data = meeting.start_at.strftime("%Y-%m-%dT%H:%M")
        form.end_at.data = meeting.end_at.strftime("%Y-%m-%dT%H:%M")

    return render_template(
        "members/comision_reunion_form.html",
        form=form,
        commission=commission,
        meeting=meeting,
    )


@members_bp.route("/calendario")
@login_required
def calendar():
    if not current_user.has_permission("view_private_calendar"):
        abort(403)
    return render_template("members/calendario.html")
