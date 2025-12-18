from flask import Blueprint, render_template, request, flash, redirect, url_for, session, abort, jsonify, current_app
from flask_login import login_required, current_user, login_user, logout_user
from datetime import datetime, timedelta
import secrets
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


def _user_is_commission_coordinator(membership: CommissionMembership | None) -> bool:
    return bool(membership and membership.role == "coordinador")


@members_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("members.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        lookup_email = make_lookup_hash(form.email.data)
        user = User.query.filter_by(email_lookup=lookup_email).first()
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash("Tu cuenta está desactivada.", "danger")
                return render_template("members/login.html", form=form)
            if not user.email_verified:
                flash("Debes verificar tu correo antes de iniciar sesión.", "warning")
                return render_template("members/login.html", form=form)
            if not user.registration_approved:
                flash("Tu alta está pendiente de aprobación.", "info")
                return render_template("members/login.html", form=form)

            login_user(user, remember=form.remember_me.data)
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash("Bienvenido de nuevo", "success")
            return redirect(url_for("members.dashboard"))
        flash("Credenciales inválidas", "danger")
    return render_template("members/login.html", form=form)


@members_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("members.dashboard"))

    if Permission.supports_public_flag():
        try:
            is_public = db.session.query(Permission.is_public).filter_by(key="public_registration").scalar()
            if is_public is False:
                flash("El registro de socios está cerrado temporalmente.", "info")
                return redirect(url_for("public.home"))
        except Exception:
            pass

    form = RegisterForm()
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
                result = send_member_verification_email(
                    recipient_email=existing_user.email,
                    verify_url=verify_url,
                    app_config=current_app.config,
                )
                if not result.get("ok"):
                    current_app.logger.error(
                        "Fallo reenviando verificación de email (registro) a %s: %s",
                        existing_user.email,
                        result.get("error"),
                    )
            flash(
                "Si el correo es valido, recibiras un enlace de verificacion. "
                "Revisa tu bandeja de entrada y, si no aparece, el correo no deseado o spam. "
                "Tu alta quedara pendiente de aprobacion.",
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
                "Si el correo es valido, recibiras un enlace de verificacion. "
                "Revisa tu bandeja de entrada y, si no aparece, el correo no deseado o spam. "
                "Tu alta quedara pendiente de aprobacion.",
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
        if not verification_result.get("ok"):
            current_app.logger.error(
                "Fallo enviando verificación de email a %s: %s",
                user.email,
                verification_result.get("error"),
            )

        full_name = f"{(user.first_name or '').strip()} {(user.last_name or '').strip()}".strip()
        notification_result = send_new_member_registration_notification_to_ampa(
            member_name=full_name or "Socio",
            member_email=user.email,
            member_phone=user.phone_number,
            app_config=current_app.config,
        )
        if not notification_result.get("ok"):
            current_app.logger.error(
                "Fallo enviando notificación interna de nuevo registro (AMPA): %s",
                notification_result.get("error"),
            )

        if verification_result.get("ok"):
            flash(
                "Registro recibido. Hemos enviado un enlace de verificacion a tu correo. "
                "Revisa tu bandeja de entrada y, si no aparece, el correo no deseado o spam. "
                "Tu alta queda pendiente de aprobacion.",
                "success",
            )
        else:
            flash(
                "Registro recibido, pero no se pudo enviar el enlace de verificación por email. "
                "Inténtalo de nuevo más tarde (reenviar verificación) o contacta con el AMPA.",
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
        return redirect(url_for("members.mi_cuenta"))

    if password_form.submit_password.data and password_form.validate_on_submit():
        if not current_user.check_password(password_form.current_password.data):
            flash("Contraseña actual incorrecta.", "danger")
            return redirect(url_for("members.mi_cuenta"))
        current_user.set_password(password_form.new_password.data)
        db.session.commit()
        flash("Contraseña actualizada.", "success")
        return redirect(url_for("members.mi_cuenta"))

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
        .order_by(Suggestion.votes_count.desc())
        .paginate(page=page, per_page=5)
    )
    return render_template("members/sugerencias.html", suggestions=suggestions, status=status)


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
        comment_form=comment_form,
        vote_form=vote_form,
        user_vote=user_vote,
        likes_count=likes_count,
        dislikes_count=dislikes_count,
        is_closed=is_closed,
    )


@members_bp.route("/sugerencias/<int:suggestion_id>/comentar", methods=["POST"])
@login_required
def comentar_sugerencia(suggestion_id: int):
    if not current_user.has_permission("comment_suggestions"):
        abort(403)
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
def votar_sugerencia(suggestion_id: int):
    if not current_user.has_permission("vote_suggestions"):
        abort(403)
    suggestion = Suggestion.query.get_or_404(suggestion_id)
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
        commission.memberships.filter_by(is_active=True)
        .order_by(CommissionMembership.role.asc())
        .all()
    )
    projects = commission.projects.order_by(CommissionProject.created_at.desc()).all()
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
    can_manage_members = current_user.has_permission("manage_commission_members") and (
        is_coordinator or current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    )
    can_manage_projects = current_user.has_permission("manage_commission_projects") and (
        is_coordinator or current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    )
    can_manage_meetings = current_user.has_permission("manage_commission_meetings") and (
        is_coordinator or current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    )
    can_edit_commission = current_user.has_permission("manage_commissions") or user_is_privileged(current_user)

    return render_template(
        "members/comision_detalle.html",
        commission=commission,
        membership=membership,
        members=members,
        projects=projects,
        upcoming_meetings=upcoming_meetings,
        past_meetings=past_meetings,
        is_coordinator=is_coordinator,
        can_manage_members=can_manage_members,
        can_manage_projects=can_manage_projects,
        can_manage_meetings=can_manage_meetings,
        can_edit_commission=can_edit_commission,
    )


@members_bp.route("/comisiones/<slug>/miembros/nuevo", methods=["GET", "POST"])
@login_required
def commission_member_new(slug: str):
    commission, membership = _get_commission_and_membership(slug)
    is_coord = _user_is_commission_coordinator(membership)
    if not (current_user.has_permission("manage_commission_members") and (is_coord or current_user.has_permission("manage_commissions") or user_is_privileged(current_user))):
        abort(403)

    form = CommissionMemberForm()
    form.user_id.choices = [(u.id, u.username) for u in User.query.filter_by(is_active=True).order_by(User.username.asc())]

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
    if not (current_user.has_permission("manage_commission_members") and (is_coord or current_user.has_permission("manage_commissions") or user_is_privileged(current_user))):
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
    if not (current_user.has_permission("manage_commission_projects") and (is_coord or current_user.has_permission("manage_commissions") or user_is_privileged(current_user))):
        abort(403)

    project = CommissionProject.query.filter_by(id=project_id, commission_id=commission.id).first() if project_id else None
    form = CommissionProjectForm(obj=project)
    user_choices = [(u.id, u.username) for u in User.query.filter_by(is_active=True).order_by(User.username.asc())]
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
    if not (current_user.has_permission("manage_commission_meetings") and (is_coord or current_user.has_permission("manage_commissions") or user_is_privileged(current_user))):
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
