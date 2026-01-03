from flask import Blueprint, render_template, request, flash, redirect, url_for, session, abort, jsonify, current_app
from flask_login import login_required, current_user, login_user, logout_user
from datetime import datetime, timedelta
import secrets
import re
from urllib.parse import urlparse
from sqlalchemy import func
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
    build_meeting_description,
    merge_meeting_description,
    get_local_now,
)
from app.services.permission_registry import ensure_roles_and_permissions, DEFAULT_ROLE_NAMES
from app.services.calendar_service import sync_commission_meeting_to_calendar
from app.services.commission_drive_service import ensure_project_drive_folder

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

    if not bool(current_app.config.get("SUGGESTIONS_FORUM_ENABLED", False)):
        return (
            url_for("members.dashboard"),
            "Volver al panel",
            f"Área privada · Discusiones · {suggestion.title}",
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
        or current_user.has_permission("manage_commission_members")
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
        or current_user.has_permission("manage_commission_members")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commission:
        abort(403)


def _ensure_can_access_scoped_discussion(suggestion: Suggestion) -> None:
    _ensure_can_access_commission_discussion(suggestion)
    _ensure_can_access_project_discussion(suggestion)


def _ensure_can_access_suggestion_detail(suggestion: Suggestion) -> None:
    category = (getattr(suggestion, "category", None) or "").strip()
    is_scoped = (
        _commission_discussion_commission_id(category) is not None
        or _project_discussion_project_id(category) is not None
    )

    # Si el foro general está deshabilitado, solo se permiten discusiones scoped
    # (comisiones/proyectos). El resto debe comportarse como si no existiera.
    if not bool(current_app.config.get("SUGGESTIONS_FORUM_ENABLED", False)) and not is_scoped:
        abort(404)

    if not current_user.has_permission("view_suggestions") and not is_scoped:
        abort(403)
    _ensure_can_access_scoped_discussion(suggestion)


def _user_can_participate_in_scoped_discussion(suggestion: Suggestion) -> bool:
    category = (getattr(suggestion, "category", None) or "").strip()
    commission_id = _commission_discussion_commission_id(category)
    if commission_id is not None:
        membership = CommissionMembership.query.filter_by(
            commission_id=commission_id, user_id=current_user.id, is_active=True
        ).first()
        return bool(membership)
    project_id = _project_discussion_project_id(category)
    if project_id is not None:
        project = CommissionProject.query.get(project_id)
        if not project:
            return False
        membership = CommissionMembership.query.filter_by(
            commission_id=project.commission_id, user_id=current_user.id, is_active=True
        ).first()
        return bool(membership)
    return False


def _vote_counts_for_suggestions(suggestion_ids: list[int]) -> dict[int, int]:
    if not suggestion_ids:
        return {}
    rows = (
        db.session.query(Vote.suggestion_id, func.count(Vote.id))
        .filter(Vote.suggestion_id.in_(suggestion_ids))
        .group_by(Vote.suggestion_id)
        .all()
    )
    return {suggestion_id: count for suggestion_id, count in rows}


def _user_is_commission_coordinator(membership: CommissionMembership | None) -> bool:
    return bool(membership and membership.role == "coordinador")

def _commission_can_manage(membership: CommissionMembership | None, area: str) -> bool:
    if not membership or not membership.is_active:
        return False
    role = (membership.role or "").strip().lower()
    if role == "coordinador":
        return area in {"members", "projects", "meetings", "discussions"}
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
    if not bool(current_app.config.get("SUGGESTIONS_FORUM_ENABLED", False)):
        abort(404)
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
        or current_user.has_permission("manage_commission_members")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commission:
        abort(403)
    if not (
        _commission_can_manage(membership, "discussions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
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


@members_bp.route("/comisiones/<slug>/discusiones/<int:suggestion_id>/editar", methods=["GET", "POST"])
@login_required
def commission_discussion_edit(slug: str, suggestion_id: int):
    commission, membership = _get_commission_and_membership(slug)
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    category_commission_id = _commission_discussion_commission_id(getattr(suggestion, "category", None))
    if category_commission_id != commission.id:
        abort(404)

    can_manage = (
        _commission_can_manage(membership, "discussions")
        or current_user.has_permission("manage_suggestions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_manage:
        abort(403)

    return_to = _safe_return_to(request.args.get("return_to"))

    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        if action == "close":
            suggestion.status = "cerrada"
            db.session.commit()
            flash("Discusión finalizada.", "success")
        elif action == "delete":
            Comment.query.filter_by(suggestion_id=suggestion.id).delete(synchronize_session=False)
            Vote.query.filter_by(suggestion_id=suggestion.id).delete(synchronize_session=False)
            db.session.delete(suggestion)
            db.session.commit()
            flash("Discusión eliminada.", "info")
        target = return_to or url_for("members.commission_detail", slug=commission.slug)
        return redirect(target)

    return render_template(
        "members/comision_discusion_edit.html",
        commission=commission,
        suggestion=suggestion,
        return_to=return_to,
        back_href=return_to or url_for("members.commission_detail", slug=commission.slug),
        back_label="Volver a comisiones",
    )


@members_bp.route("/sugerencias/nueva", methods=["GET", "POST"])
@login_required
def nueva_sugerencia():
    if not bool(current_app.config.get("SUGGESTIONS_FORUM_ENABLED", False)):
        abort(404)
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
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    _ensure_can_access_suggestion_detail(suggestion)
    return_to = _safe_return_to(request.args.get("return_to"))
    back_url, back_label, breadcrumb = _discussion_back_target(suggestion, return_to=return_to)
    comment_form = CommentForm()
    vote_form = VoteForm()
    user_vote = suggestion.votes.filter_by(user_id=current_user.id).first()
    if user_vote:
        vote_form.value.data = str(user_vote.value)
    comments = suggestion.comments.order_by(Comment.created_at.asc()).all()
    child_parent_ids = {comment.parent_id for comment in comments if comment.parent_id}
    leaf_comment_ids = {comment.id for comment in comments if comment.id not in child_parent_ids}
    likes_count = suggestion.votes.filter_by(value=1).count()
    dislikes_count = suggestion.votes.filter_by(value=-1).count()
    total_votes = likes_count + dislikes_count
    is_closed = suggestion.status == "cerrada"
    scoped_participant = _user_can_participate_in_scoped_discussion(suggestion)
    return render_template(
        "members/sugerencia_detalle.html",
        suggestion=suggestion,
        comments=comments,
        Comment=Comment,
        leaf_comment_ids=leaf_comment_ids,
        comment_form=comment_form,
        vote_form=vote_form,
        user_vote=user_vote,
        likes_count=likes_count,
        dislikes_count=dislikes_count,
        total_votes=total_votes,
        is_closed=is_closed,
        can_comment=current_user.has_permission("comment_suggestions") or scoped_participant,
        can_vote=current_user.has_permission("vote_suggestions") or scoped_participant,
        back_url=back_url,
        back_label=back_label,
        breadcrumb=breadcrumb,
    )


@members_bp.route("/sugerencias/<int:suggestion_id>/comentar", methods=["POST"])
@login_required
def comentar_sugerencia(suggestion_id: int):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    _ensure_can_access_suggestion_detail(suggestion)
    if not current_user.has_permission("comment_suggestions") and not _user_can_participate_in_scoped_discussion(suggestion):
        abort(403)
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


@members_bp.route("/comentarios/<int:comment_id>/eliminar", methods=["POST"])
@login_required
def eliminar_comentario(comment_id: int):
    comment = Comment.query.get_or_404(comment_id)
    if comment.created_by != current_user.id:
        abort(403)
    suggestion = comment.suggestion
    if not suggestion:
        abort(404)
    _ensure_can_access_suggestion_detail(suggestion)
    if comment.children.count() > 0:
        flash("Solo puedes eliminar tu ultimo mensaje si no hay respuestas posteriores.", "warning")
        return redirect(url_for("members.detalle_sugerencia", suggestion_id=comment.suggestion_id))
    db.session.delete(comment)
    db.session.commit()
    flash("Comentario eliminado", "success")
    return redirect(url_for("members.detalle_sugerencia", suggestion_id=comment.suggestion_id))


@members_bp.route("/comentarios/<int:comment_id>/editar", methods=["POST"])
@login_required
def editar_comentario(comment_id: int):
    comment = Comment.query.get_or_404(comment_id)
    if comment.created_by != current_user.id:
        abort(403)

    suggestion = comment.suggestion
    if not suggestion:
        abort(404)
    _ensure_can_access_suggestion_detail(suggestion)

    # Solo se permite editar si nadie ha respondido a este comentario.
    if comment.children.count() > 0:
        flash("Solo puedes editar tu ultimo mensaje si no hay respuestas posteriores.", "warning")
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
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    _ensure_can_access_suggestion_detail(suggestion)
    if not current_user.has_permission("vote_suggestions") and not _user_can_participate_in_scoped_discussion(suggestion):
        abort(403)
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

        is_new_vote = False
        if vote:
            vote.value = value
        else:
            vote = Vote(suggestion_id=suggestion.id, user_id=current_user.id, value=value)
            db.session.add(vote)
            is_new_vote = True
        existing_votes = Vote.query.filter_by(suggestion_id=suggestion.id).count()
        suggestion.votes_count = existing_votes + (1 if is_new_vote else 0)
        db.session.commit()
        likes_count = suggestion.votes.filter_by(value=1).count()
        dislikes_count = suggestion.votes.filter_by(value=-1).count()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(
                success=True,
                message="Voto actualizado" if not is_new_vote else "Voto registrado",
                vote=value,
                likes=likes_count,
                dislikes=dislikes_count,
            )
        flash("Voto actualizado" if not is_new_vote else "Voto registrado", "success")
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

    # Los usuarios sin permiso view_commissions solo pueden ver sus comisiones
    query = Commission.query.filter_by(is_active=True)
    if not can_view_all:
        commission_ids = list(memberships_map.keys())
        query = query.filter(Commission.id.in_(commission_ids)) if commission_ids else query.filter(Commission.id == -1)

    commissions = query.order_by(Commission.name.asc()).all()
    stats: dict[int, dict[str, object]] = {}
    now_dt = get_local_now()
    active_project_statuses = ("pendiente", "en_progreso")
    for commission in commissions:
        members_count = (
            commission.memberships.join(User)
            .filter(
                CommissionMembership.is_active.is_(True),
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
            .count()
        )
        active_projects_count = commission.projects.filter(CommissionProject.status.in_(active_project_statuses)).count()
        next_meeting = (
            commission.meetings.filter(
                CommissionMeeting.project_id.is_(None),
                CommissionMeeting.start_at >= now_dt,
            )
            .order_by(CommissionMeeting.start_at.asc())
            .first()
        )
        stats[commission.id] = {
            "miembros": members_count,
            "proyectos_activos": active_projects_count,
            "proxima_reunion": next_meeting,
        }

    return render_template(
        "admin/comisiones.html",
        commissions=commissions,
        stats=stats,
        scope=scope,
        can_view_all=can_view_all,
        is_member_view=True,
        header_kicker="Área privada",
        header_title="Comisiones del AMPA",
        header_subtitle="Consulta las comisiones en las que participas.",
        empty_text="No perteneces a ninguna comisión activa.",
        show_create_button=False,
        show_empty_action=False,
    )


@members_bp.route("/comisiones/<slug>")
@login_required
def commission_detail(slug: str):
    commission, membership = _get_commission_and_membership(slug)
    can_view_commission = (
        bool(membership)
        or current_user.has_permission("manage_commission_members")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commission:
        abort(403)

    members_active = (
        commission.memberships.join(User)
        .filter(
            CommissionMembership.is_active.is_(True),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
        )
        .all()
    )
    members_active = sorted(
        members_active,
        key=lambda membership: (
            0 if (membership.role or "").lower() == "coordinador" else 1,
            (membership.user.display_name if membership.user else "").casefold(),
        ),
    )
    members_list = [
        {
            "name": m.user.display_name if m.user else "Usuario",
            "role": (m.role or "").replace("_", " "),
        }
        for m in members_active
    ]
    active_project_statuses = ("pendiente", "en_progreso")
    active_projects = (
        commission.projects
        .filter(CommissionProject.status.in_(active_project_statuses))
        .order_by(CommissionProject.created_at.desc())
        .all()
    )

    commission_discussions = (
        Suggestion.query.filter(
            Suggestion.category == f"comision:{commission.id}",
            Suggestion.status.in_(("pendiente", "aprobada")),
        )
        .order_by(Suggestion.updated_at.desc())
        .limit(20)
        .all()
    )
    discussion_vote_counts = _vote_counts_for_suggestions([discussion.id for discussion in commission_discussions])
    now_dt = get_local_now()
    upcoming_meetings = (
        commission.meetings.filter(
            CommissionMeeting.project_id.is_(None),
            CommissionMeeting.end_at >= now_dt,
        )
        .order_by(CommissionMeeting.start_at.asc())
        .all()
    )
    past_meetings = (
        commission.meetings.filter(
            CommissionMeeting.project_id.is_(None),
            CommissionMeeting.end_at < now_dt,
        )
        .order_by(CommissionMeeting.start_at.desc())
        .all()
    )

    can_manage_members = (
        _commission_can_manage(membership, "members")
        or current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    )
    can_manage_projects = (
        _commission_can_manage(membership, "projects")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    can_manage_meetings = (
        _commission_can_manage(membership, "meetings")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    can_edit_commission = current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    can_manage_discussions = (
        _commission_can_manage(membership, "discussions")
        or current_user.has_permission("manage_suggestions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    can_create_discussions = can_manage_discussions
    can_manage_drive_files = (
        _user_is_commission_coordinator(membership)
        or current_user.has_permission("manage_commission_drive_files")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    can_view_drive_history = can_manage_drive_files or current_user.has_permission("view_commission_drive_history")

    next_meeting = upcoming_meetings[0] if upcoming_meetings else None

    return render_template(
        "admin/comision_detalle.html",
        commission=commission,
        members_count=len(members_list),
        members_list=members_list,
        active_projects=active_projects,
        next_meeting=next_meeting,
        upcoming_meetings=upcoming_meetings,
        past_meetings=past_meetings,
        discussions=commission_discussions,
        discussion_vote_counts=discussion_vote_counts,
        is_member_view=True,
        can_manage_discussions=can_manage_discussions,
        header_kicker=f"Comisiones \u00b7 {commission.name}",
        back_href=url_for("members.commissions"),
        back_label="Volver a comisiones",
        return_to_url=url_for("members.commission_detail", slug=commission.slug),
        member_role=membership.role if membership else None,
        can_manage_members=can_manage_members,
        can_manage_projects=can_manage_projects,
        can_manage_meetings=can_manage_meetings,
        can_edit_commission=can_edit_commission,
        can_create_discussions=can_create_discussions,
        can_manage_drive_files=can_manage_drive_files,
        can_view_drive_history=can_view_drive_history,
    )


@members_bp.route("/comisiones/<slug>/proyectos/<int:project_id>")
@login_required
def commission_project_detail(slug: str, project_id: int):
    commission, membership = _get_commission_and_membership(slug)
    return_to = _safe_return_to(request.args.get("return_to"))
    can_view_commission = (
        bool(membership)
        or current_user.has_permission("manage_commission_members")
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
    project_discussion_vote_counts = _vote_counts_for_suggestions([discussion.id for discussion in project_discussions])
    now_dt = get_local_now()
    project_upcoming_meetings = (
        CommissionMeeting.query.filter_by(
            commission_id=commission.id,
            project_id=project.id,
        )
        .filter(CommissionMeeting.end_at >= now_dt)
        .order_by(CommissionMeeting.start_at.asc())
        .all()
    )
    project_past_meetings = (
        CommissionMeeting.query.filter_by(
            commission_id=commission.id,
            project_id=project.id,
        )
        .filter(CommissionMeeting.end_at < now_dt)
        .order_by(CommissionMeeting.start_at.desc())
        .all()
    )

    can_create_discussions = (
        _commission_can_manage(membership, "discussions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    can_manage_projects = (
        _commission_can_manage(membership, "projects")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    can_manage_meetings = (
        _commission_can_manage(membership, "meetings")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    can_manage_drive_files = (
        _user_is_commission_coordinator(membership)
        or current_user.has_permission("manage_commission_drive_files")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    can_view_drive_history = can_manage_drive_files or current_user.has_permission("view_commission_drive_history")

    if return_to:
        back_url = return_to
        back_label = "Volver a comisión"
    else:
        back_url = url_for("members.commission_detail", slug=commission.slug)
        back_label = "Volver a comisión"

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
        project_discussion_vote_counts=project_discussion_vote_counts,
        project_upcoming_meetings=project_upcoming_meetings,
        project_past_meetings=project_past_meetings,
        can_create_discussions=can_create_discussions,
        can_manage_projects=can_manage_projects,
        can_manage_meetings=can_manage_meetings,
        can_manage_drive_files=can_manage_drive_files,
        can_view_drive_history=can_view_drive_history,
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
        or current_user.has_permission("manage_commission_members")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commission:
        abort(403)
    if not (
        _commission_can_manage(membership, "discussions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
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
    can_manage_members = (
        _commission_can_manage(membership, "members")
        or current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    )
    if not can_manage_members:
        abort(403)

    form = CommissionMemberForm()
    active_users = (
        User.query.filter_by(is_active=True, registration_approved=True)
        .filter(User.deleted_at.is_(None))
        .all()
    )
    active_users_sorted = sorted(active_users, key=lambda user: user.display_name.casefold())
    active_users_map = {user.id: user.display_name for user in active_users_sorted}
    from sqlalchemy.orm import joinedload

    memberships = (
        commission.memberships.options(joinedload(CommissionMembership.user))
        .order_by(CommissionMembership.created_at.desc())
        .all()
    )
    members_active = [
        m
        for m in memberships
        if m.is_active and m.user.is_active and m.user.deleted_at is None
    ]
    active_member_user_ids = {m.user_id for m in members_active}
    active_member_user_ids = {m.user_id for m in members_active}
    active_member_ids = {m.id for m in members_active}
    members_history = [m for m in memberships if m.id not in active_member_ids]

    choices = [(0, "-Selecciona un miembro-")] + [
        (user.id, user.display_name)
        for user in active_users_sorted
        if user.id not in active_member_user_ids
    ]
    if request.method == "POST":
        selected_user_id = form.user_id.data or 0
        if selected_user_id in active_member_user_ids:
            if selected_user_id not in {value for value, _ in choices}:
                choices.append((selected_user_id, active_users_map.get(selected_user_id, "Miembro")))
    form.user_id.choices = choices
    if request.method == "GET":
        form.user_id.default = 0
        form.role.default = "miembro"
        form.process(formdata=None)

    if form.validate_on_submit():
        existing = CommissionMembership.query.filter_by(
            commission_id=commission.id, user_id=form.user_id.data
        ).first()
        if existing:
            existing.role = form.role.data
            existing.is_active = True
        else:
            membership_obj = CommissionMembership(
                commission_id=commission.id,
                user_id=form.user_id.data,
                role=form.role.data,
                is_active=True,
            )
            db.session.add(membership_obj)
        db.session.commit()
        flash("Miembro guardado en la comisión", "success")
        return redirect(url_for("members.commission_member_new", slug=slug))

    return render_template(
        "admin/comision_miembros.html",
        commission=commission,
        members_active=members_active,
        members_history=members_history,
        form=form,
        is_member_view=True,
        back_href=url_for("members.commission_detail", slug=commission.slug),
        back_label="Volver a comisiones",
        header_kicker="Comisiones - Area privada",
    )


@members_bp.route("/comisiones/<slug>/miembros/<int:membership_id>/desactivar", methods=["POST"])
@login_required
def commission_member_disable(slug: str, membership_id: int):
    commission, membership = _get_commission_and_membership(slug)
    can_manage_members = (
        _commission_can_manage(membership, "members")
        or current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    )
    if not can_manage_members:
        abort(403)

    target = CommissionMembership.query.filter_by(id=membership_id, commission_id=commission.id).first_or_404()
    target.is_active = False
    db.session.commit()
    flash("Miembro desactivado", "info")
    return redirect(url_for("members.commission_member_new", slug=slug))


@members_bp.route("/comisiones/<slug>/miembros/<int:membership_id>/reactivar", methods=["POST"])
@login_required
def commission_member_reactivate(slug: str, membership_id: int):
    commission, membership = _get_commission_and_membership(slug)
    can_manage_members = (
        _commission_can_manage(membership, "members")
        or current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    )
    if not can_manage_members:
        abort(403)

    target = CommissionMembership.query.filter_by(id=membership_id, commission_id=commission.id).first_or_404()
    target.is_active = True
    db.session.commit()
    flash("Miembro reactivado", "success")
    return redirect(url_for("members.commission_member_new", slug=slug))


@members_bp.route("/comisiones/<slug>/proyectos/nuevo", methods=["GET", "POST"])
@members_bp.route("/comisiones/<slug>/proyectos/<int:project_id>/editar", methods=["GET", "POST"])
@login_required
def commission_project_form(slug: str, project_id: int | None = None):
    commission, membership = _get_commission_and_membership(slug)
    if not (
        _commission_can_manage(membership, "projects")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
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
        should_sync_drive = False
        if project:
            new_title = form.title.data
            title_changed = new_title != (project.title or "")
            project.title = new_title
            project.description_html = form.description.data
            project.status = form.status.data
            project.start_date = form.start_date.data
            project.end_date = form.end_date.data
            project.responsible_id = responsible_id
            should_sync_drive = title_changed or not (project.drive_folder_id or "").strip()
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
            should_sync_drive = True
        db.session.commit()
        if should_sync_drive:
            try:
                ensure_project_drive_folder(project)
            except Exception as exc:  # noqa: BLE001
                current_app.logger.warning(
                    "No se pudo sincronizar carpeta de Drive para el proyecto %s: %s",
                    project.id,
                    exc,
                )
        flash("Proyecto guardado", "success")
        return redirect(url_for("members.commission_detail", slug=slug))

    if request.method == "GET" and project:
        form.responsible_id.data = project.responsible_id or 0

    return render_template(
        "shared/comision_proyecto_form.html",
        form=form,
        commission=commission,
        project=project,
        header_kicker="Comisiones - Area privada",
        back_href=url_for("members.commission_detail", slug=commission.slug),
        back_label="Cancelar",
    )


@members_bp.route("/comisiones/<slug>/reuniones/nueva", methods=["GET", "POST"])
@members_bp.route("/comisiones/<slug>/reuniones/<int:meeting_id>/editar", methods=["GET", "POST"])
@login_required
def commission_meeting_form(slug: str, meeting_id: int | None = None):
    commission, membership = _get_commission_and_membership(slug)
    if not (
        _commission_can_manage(membership, "meetings")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)

    meeting = (
        CommissionMeeting.query.filter_by(
            id=meeting_id,
            commission_id=commission.id,
            project_id=None,
        ).first()
        if meeting_id
        else None
    )
    
    # Preparar los datos iniciales del formulario si es una edición
    if meeting and request.method == "GET":
        form = CommissionMeetingForm(
            title=meeting.title,
            description=meeting.description_html,
            location=meeting.location,
            start_at=meeting.start_at.strftime("%Y-%m-%dT%H:%M"),
            end_at=meeting.end_at.strftime("%Y-%m-%dT%H:%M"),
        )
    else:
        form = CommissionMeetingForm()
    
    document_choices = [(0, "Sin acta")] + [
        (doc.id, doc.title or f"Documento {doc.id}") for doc in Document.query.order_by(Document.created_at.desc()).all()
    ]
    form.minutes_document_id.choices = document_choices
    
    # Asignar el valor del select después de definir las opciones
    if meeting and request.method == "GET":
        form.minutes_document_id.data = meeting.minutes_document_id or 0
    
    default_description = build_meeting_description(commission.name)
    back_url = url_for("members.commission_detail", slug=commission.slug)
    back_label = "Volver a la comisión"
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")

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
                back_url=back_url,
                back_label=back_label,
                now_str=now_str,
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
            is_new_meeting = False
        else:
            description_value = merge_meeting_description(default_description, form.description.data)
            meeting = CommissionMeeting(
                commission_id=commission.id,
                title=form.title.data,
                description_html=description_value,
                start_at=start_at,
                end_at=end_at,
                location=form.location.data,
                minutes_document_id=minutes_document_id,
            )
            db.session.add(meeting)
            is_new_meeting = True
        
        db.session.commit()
        calendar_result = sync_commission_meeting_to_calendar(meeting, commission)
        if calendar_result.get("ok"):
            event_id = calendar_result.get("event_id")
            if event_id and meeting.google_event_id != event_id:
                meeting.google_event_id = event_id
                db.session.commit()
        else:
            current_app.logger.warning(
                "No se pudo sincronizar la reunion con Google Calendar: %s",
                calendar_result.get("error"),
            )
            flash("Reunión guardada, pero no se pudo sincronizar con Google Calendar.", "warning")
        
        # Enviar notificaciones por correo (tanto para nuevas como para ediciones)
        from app.services.mail_service import send_meeting_notification
        
        # Obtener todos los miembros activos de la comisión
        active_members = CommissionMembership.query.filter_by(
            commission_id=commission.id,
            is_active=True
        ).all()
        
        notifications_sent = 0
        notifications_failed = 0
        
        for membership in active_members:
            user = membership.user
            if user and user.email and user.is_active:
                try:
                    result = send_meeting_notification(
                        meeting=meeting,
                        commission=commission,
                        recipient_email=user.email,
                        recipient_name=user.full_name or user.username,
                        app_config=current_app.config,
                        is_update=not is_new_meeting,
                    )
                    if result.get("ok"):
                        notifications_sent += 1
                    else:
                        notifications_failed += 1
                        current_app.logger.warning(
                            "No se pudo enviar notificación de reunión a %s: %s",
                            user.email,
                            result.get("error"),
                        )
                except Exception as e:
                    notifications_failed += 1
                    current_app.logger.error(
                        "Error enviando notificación de reunión a %s: %s",
                        user.email,
                        str(e),
                    )
        
        if is_new_meeting:
            if notifications_sent > 0:
                flash(f"Reunión guardada y {notifications_sent} notificación(es) enviada(s)", "success")
            else:
                flash("Reunión guardada", "success")
        else:
            if notifications_sent > 0:
                flash(f"Reunión actualizada y {notifications_sent} notificación(es) de actualización enviada(s)", "success")
            else:
                flash("Reunión actualizada", "success")
        
        if notifications_failed > 0:
            flash(f"No se pudieron enviar {notifications_failed} notificación(es)", "warning")
        
        return redirect(url_for("members.commission_detail", slug=slug))

    # Para reuniones nuevas, asignar descripción por defecto
    if request.method == "GET" and not meeting and not form.description.data:
        form.description.data = default_description

    return render_template(
        "members/comision_reunion_form.html",
        form=form,
        commission=commission,
        meeting=meeting,
        back_url=back_url,
        back_label=back_label,
        now_str=now_str,
    )


@members_bp.route(
    "/comisiones/<slug>/proyectos/<int:project_id>/reuniones/nueva",
    methods=["GET", "POST"],
)
@members_bp.route(
    "/comisiones/<slug>/proyectos/<int:project_id>/reuniones/<int:meeting_id>/editar",
    methods=["GET", "POST"],
)
@login_required
def project_meeting_form(slug: str, project_id: int, meeting_id: int | None = None):
    commission, membership = _get_commission_and_membership(slug)
    if not (
        _commission_can_manage(membership, "meetings")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)

    project = CommissionProject.query.filter_by(id=project_id, commission_id=commission.id).first_or_404()
    meeting = (
        CommissionMeeting.query.filter_by(
            id=meeting_id,
            commission_id=commission.id,
            project_id=project.id,
        ).first()
        if meeting_id
        else None
    )
    
    # Preparar los datos iniciales del formulario si es una edición
    if meeting and request.method == "GET":
        form = CommissionMeetingForm(
            title=meeting.title,
            description=meeting.description_html,
            location=meeting.location,
            start_at=meeting.start_at.strftime("%Y-%m-%dT%H:%M"),
            end_at=meeting.end_at.strftime("%Y-%m-%dT%H:%M"),
        )
    else:
        form = CommissionMeetingForm()
    
    document_choices = [(0, "Sin acta")] + [
        (doc.id, doc.title or f"Documento {doc.id}") for doc in Document.query.order_by(Document.created_at.desc()).all()
    ]
    form.minutes_document_id.choices = document_choices
    
    # Asignar el valor del select después de definir las opciones
    if meeting and request.method == "GET":
        form.minutes_document_id.data = meeting.minutes_document_id or 0
    
    default_description = build_meeting_description(commission.name, project.title)

    return_to = _safe_return_to(request.args.get("return_to"))
    project_self_url = url_for(
        "members.commission_project_detail",
        slug=commission.slug,
        project_id=project.id,
        return_to=return_to,
    )
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")

    if form.validate_on_submit():
        start_at = _parse_datetime_local(form.start_at.data)
        end_at = _parse_datetime_local(form.end_at.data)
        if not start_at or not end_at or end_at <= start_at:
            flash("Fechas de inicio y fin deben ser validas y fin posterior a inicio.", "warning")
            return render_template(
                "members/comision_reunion_form.html",
                form=form,
                commission=commission,
                project=project,
                meeting=meeting,
                back_url=project_self_url,
                back_label="Volver al proyecto",
                return_to=return_to,
                now_str=now_str,
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
            is_new_meeting = False
        else:
            description_value = merge_meeting_description(default_description, form.description.data)
            meeting = CommissionMeeting(
                commission_id=commission.id,
                project_id=project.id,
                title=form.title.data,
                description_html=description_value,
                start_at=start_at,
                end_at=end_at,
                location=form.location.data,
                minutes_document_id=minutes_document_id,
            )
            db.session.add(meeting)
            is_new_meeting = True
        
        db.session.commit()
        calendar_result = sync_commission_meeting_to_calendar(meeting, commission)
        if calendar_result.get("ok"):
            event_id = calendar_result.get("event_id")
            if event_id and meeting.google_event_id != event_id:
                meeting.google_event_id = event_id
                db.session.commit()
        else:
            current_app.logger.warning(
                "No se pudo sincronizar la reunion con Google Calendar: %s",
                calendar_result.get("error"),
            )
            flash("Reunion guardada, pero no se pudo sincronizar con Google Calendar.", "warning")
        
        # Enviar notificaciones por correo (tanto para nuevas como para ediciones)
        from app.services.mail_service import send_meeting_notification
        
        # Obtener todos los miembros activos de la comisión
        active_members = CommissionMembership.query.filter_by(
            commission_id=commission.id,
            is_active=True
        ).all()
        
        notifications_sent = 0
        notifications_failed = 0
        
        for membership in active_members:
            user = membership.user
            if user and user.email and user.is_active:
                try:
                    result = send_meeting_notification(
                        meeting=meeting,
                        commission=commission,
                        recipient_email=user.email,
                        recipient_name=user.full_name or user.username,
                        app_config=current_app.config,
                        is_update=not is_new_meeting,
                    )
                    if result.get("ok"):
                        notifications_sent += 1
                    else:
                        notifications_failed += 1
                        current_app.logger.warning(
                            "No se pudo enviar notificación de reunión a %s: %s",
                            user.email,
                            result.get("error"),
                        )
                except Exception as e:
                    notifications_failed += 1
                    current_app.logger.error(
                        "Error enviando notificación de reunión a %s: %s",
                        user.email,
                        str(e),
                    )
        
        if is_new_meeting:
            if notifications_sent > 0:
                flash(f"Reunión guardada y {notifications_sent} notificación(es) enviada(s)", "success")
            else:
                flash("Reunión guardada", "success")
        else:
            if notifications_sent > 0:
                flash(f"Reunión actualizada y {notifications_sent} notificación(es) de actualización enviada(s)", "success")
            else:
                flash("Reunión actualizada", "success")
        
        if notifications_failed > 0:
            flash(f"No se pudieron enviar {notifications_failed} notificación(es)", "warning")
        
        return redirect(project_self_url)

    # Para reuniones nuevas, asignar descripción por defecto
    if request.method == "GET" and not meeting and not form.description.data:
        form.description.data = default_description

    return render_template(
        "members/comision_reunion_form.html",
        form=form,
        commission=commission,
        project=project,
        meeting=meeting,
        back_url=project_self_url,
        back_label="Volver al proyecto",
        return_to=return_to,
        now_str=now_str,
    )


@members_bp.route(
    "/comisiones/<slug>/proyectos/<int:project_id>/reuniones/<int:meeting_id>/eliminar",
    methods=["POST"],
)
@login_required
def project_meeting_delete(slug: str, project_id: int, meeting_id: int):
    """Elimina una reunion de un proyecto."""
    commission, membership = _get_commission_and_membership(slug)
    if not (
        _commission_can_manage(membership, "meetings")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)

    project = CommissionProject.query.filter_by(id=project_id, commission_id=commission.id).first_or_404()
    meeting = CommissionMeeting.query.filter_by(
        id=meeting_id,
        commission_id=commission.id,
        project_id=project.id,
    ).first_or_404()

    # Enviar correos de cancelación a todos los miembros activos de la comisión
    active_members = CommissionMembership.query.filter_by(
        commission_id=commission.id,
        is_active=True
    ).all()
    
    from app.services.mail_service import send_meeting_cancellation_notification
    
    for member in active_members:
        user = member.user
        if user and user.email:
            try:
                send_meeting_cancellation_notification(
                    meeting=meeting,
                    commission=commission,
                    recipient_email=user.email,
                    recipient_name=user.full_name or user.username,
                    app_config=current_app.config,
                )
            except Exception as e:
                current_app.logger.error(
                    f"Error enviando correo de cancelación a {user.email}: {str(e)}"
                )

    if meeting.google_event_id:
        from app.services.calendar_service import delete_commission_meeting_event
        delete_result = delete_commission_meeting_event(meeting.google_event_id)
        if not delete_result.get("ok"):
            current_app.logger.warning(
                "No se pudo eliminar el evento de Google Calendar: %s",
                delete_result.get("error"),
            )
            flash("Reunion eliminada localmente, pero no se pudo eliminar del calendario de Google.", "warning")

    db.session.delete(meeting)
    db.session.commit()
    flash("Reunion eliminada y notificaciones de cancelación enviadas", "success")

    return_to = _safe_return_to(request.args.get("return_to"))
    return redirect(
        url_for(
            "members.commission_project_detail",
            slug=commission.slug,
            project_id=project.id,
            return_to=return_to,
        )
    )


@members_bp.route("/comisiones/<slug>/reuniones/<int:meeting_id>/eliminar", methods=["POST"])
@login_required
def commission_meeting_delete(slug: str, meeting_id: int):
    """Elimina una reunión de la comisión."""
    commission, membership = _get_commission_and_membership(slug)
    if not (
        _commission_can_manage(membership, "meetings")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)

    meeting = CommissionMeeting.query.filter_by(
        id=meeting_id,
        commission_id=commission.id,
        project_id=None,
    ).first_or_404()
    
    # Enviar correos de cancelación a todos los miembros activos de la comisión
    active_members = CommissionMembership.query.filter_by(
        commission_id=commission.id,
        is_active=True
    ).all()
    
    from app.services.mail_service import send_meeting_cancellation_notification
    
    for member in active_members:
        user = member.user
        if user and user.email:
            try:
                send_meeting_cancellation_notification(
                    meeting=meeting,
                    commission=commission,
                    recipient_email=user.email,
                    recipient_name=user.full_name or user.username,
                    app_config=current_app.config,
                )
            except Exception as e:
                current_app.logger.error(
                    f"Error enviando correo de cancelación a {user.email}: {str(e)}"
                )
    
    # Intentar eliminar del calendario de Google si existe
    if meeting.google_event_id:
        from app.services.calendar_service import delete_commission_meeting_event
        delete_result = delete_commission_meeting_event(meeting.google_event_id)
        if not delete_result.get("ok"):
            current_app.logger.warning(
                "No se pudo eliminar el evento de Google Calendar: %s",
                delete_result.get("error"),
            )
            flash("Reunión eliminada localmente, pero no se pudo eliminar del calendario de Google.", "warning")
    
    # Eliminar de la base de datos
    db.session.delete(meeting)
    db.session.commit()
    
    flash("Reunión eliminada y notificaciones de cancelación enviadas", "success")
    return redirect(url_for("members.commission_detail", slug=slug))


@members_bp.route("/comisiones/<slug>/reuniones")
@login_required
def commission_meetings_list(slug: str):
    """Lista todas las reuniones de una comisión con filtros y búsqueda."""
    commission, membership = _get_commission_and_membership(slug)
    can_view_commission = (
        bool(membership)
        or current_user.has_permission("manage_commission_members")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commission:
        abort(403)
    
    can_manage_meetings = (
        _commission_can_manage(membership, "meetings")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    
    # Parámetros de filtrado
    search_query = request.args.get("search", "").strip()
    meeting_type = request.args.get("type", "all")  # "all", "upcoming", "past"
    sort_by = request.args.get("sort", "date_desc")  # "date_asc", "date_desc", "title_asc", "title_desc"
    
    # Consulta base
    query = CommissionMeeting.query.filter_by(
        commission_id=commission.id,
        project_id=None,
    )
    
    # Búsqueda por título o ubicación
    if search_query:
        query = query.filter(
            (CommissionMeeting.title.ilike(f"%{search_query}%")) |
            (CommissionMeeting.location.ilike(f"%{search_query}%"))
        )
    
    # Filtrado por tipo
    now_dt = get_local_now()
    if meeting_type == "upcoming":
        query = query.filter(CommissionMeeting.end_at >= now_dt)
    elif meeting_type == "past":
        query = query.filter(CommissionMeeting.end_at < now_dt)
    
    # Ordenamiento
    if sort_by == "date_asc":
        query = query.order_by(CommissionMeeting.start_at.asc())
    elif sort_by == "date_desc":
        query = query.order_by(CommissionMeeting.start_at.desc())
    elif sort_by == "title_asc":
        query = query.order_by(CommissionMeeting.title.asc())
    elif sort_by == "title_desc":
        query = query.order_by(CommissionMeeting.title.desc())
    else:
        query = query.order_by(CommissionMeeting.start_at.desc())
    
    meetings = query.all()
    
    # Separar próximas y pasadas
    upcoming = [m for m in meetings if m.end_at >= now_dt]
    past = [m for m in meetings if m.end_at < now_dt]
    
    return render_template(
        "members/comision_reuniones_lista.html",
        commission=commission,
        meetings=meetings,
        upcoming_meetings=upcoming,
        past_meetings=past,
        can_manage_meetings=can_manage_meetings,
        search_query=search_query,
        meeting_type=meeting_type,
        sort_by=sort_by,
    )


@members_bp.route("/calendario")
@login_required
def calendar():
    membership = (
        CommissionMembership.query.filter_by(user_id=current_user.id, is_active=True)
        .join(Commission)
        .filter(Commission.is_active.is_(True))
        .first()
    )
    if not (membership or current_user.has_permission("view_private_calendar")):
        abort(403)
    return render_template("members/calendario.html")
