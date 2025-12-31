from flask import Blueprint, render_template, request, flash, redirect, url_for, abort, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime
import re
import unicodedata
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from email_validator import validate_email, EmailNotValidError

from app.extensions import db, csrf
from app.models import (
    Post,
    Event,
    User,
    Document,
    Enrollment,
    Membership,
    Suggestion,
    Comment,
    Vote,
    Media,
    Commission,
    CommissionMembership,
    CommissionProject,
    CommissionMeeting,
    Role,
    Permission,
    RolePermission,
    user_is_privileged,
    _generate_unique_event_slug,
    _generate_unique_commission_slug,
)
from app.services.mail_service import (
    send_member_deactivation_email,
    send_member_reactivation_email
)
from app.services.calendar_service import sync_commission_meeting_to_calendar
from app.forms import (
    PostForm,
    EventForm,
    CommissionForm,
    CommissionMemberForm,
    CommissionProjectForm,
    CommissionMeetingForm,
    EVENT_CATEGORY_LABELS,
)
from app.utils import (
    slugify,
    _normalize_drive_url,
    _parse_datetime_local,
    make_lookup_hash,
    build_meeting_description,
    merge_meeting_description,
)
from app.media_utils import upload_news_image_variants, delete_news_images
from app.services.permission_registry import (
    DEFAULT_ROLE_NAMES,
    ensure_roles_and_permissions,
    group_permissions_by_section,
    PERMISSION_DEFINITIONS,
)
from config import PRIVILEGED_ROLES

admin_bp = Blueprint("admin", __name__, template_folder="../../templates/admin")


@admin_bp.route("/")
@login_required
def dashboard_admin():
    if not (current_user.has_permission("access_admin_panel") or user_is_privileged(current_user)):
        abort(403)
    return render_template("admin/dashboard.html")


@admin_bp.route("/posts", methods=["GET", "POST"])
@login_required
def posts():
    can_edit_posts = current_user.has_permission("manage_posts") or user_is_privileged(current_user)
    can_view_posts = can_edit_posts or current_user.has_permission("view_posts")
    if request.method == "POST" and not can_edit_posts:
        abort(403)
    if request.method == "GET" and not can_view_posts:
        abort(403)

    form = PostForm()
    if request.method == "GET" and not form.published_at.data:
        form.published_at.data = datetime.utcnow().date()

    recent_posts = (
        Post.query.order_by(Post.published_at.desc().nullslast(), Post.created_at.desc())
        .all()
    )
    for rp in recent_posts:
        normalized_cover = _normalize_drive_url(rp.cover_image) or rp.cover_image
        variants = rp.image_variants or {}
        if isinstance(variants, dict) and variants:
            rp.cover_image = (
                variants.get("latest")
                or variants.get("last_h")
                or variants.get("last_v")
                or normalized_cover
            )
            rp.modal_image = (
                variants.get("modal")
                or variants.get("modal_h")
                or variants.get("modal_v")
                or rp.cover_image
            )
        else:
            rp.cover_image = normalized_cover
            rp.modal_image = normalized_cover

    if form.validate_on_submit():
        post: Post | None = None
        if form.post_id.data:
            try:
                post = Post.query.get(int(form.post_id.data))
            except Exception:
                post = None

        base_slug = slugify(form.title.data)
        slug_value = None
        if post:
            slug_value = post.slug or base_slug
            if form.title.data and post.slug:
                slug_candidate = base_slug
                counter = 2
                existing = Post.query.filter(Post.slug == slug_candidate, Post.id != post.id).first()
                while existing:
                    slug_candidate = f"{base_slug}-{counter}"
                    existing = Post.query.filter(Post.slug == slug_candidate, Post.id != post.id).first()
                    counter += 1
                slug_value = slug_candidate
        else:
            slug_candidate = base_slug
            counter = 2
            existing = Post.query.filter_by(slug=slug_candidate).first()
            while existing:
                slug_candidate = f"{base_slug}-{counter}"
                existing = Post.query.filter_by(slug=slug_candidate).first()
                counter += 1
            slug_value = slug_candidate

        content_html = form.content.data or ""
        content_text = re.sub(r"<[^>]+>", "", content_html).strip()
        if not content_text:
            flash("Añade contenido a la noticia.", "warning")
            return render_template("admin/posts.html", form=form, posts=recent_posts)

        published_at = None
        if form.published_at.data:
            published_at = datetime.combine(form.published_at.data, datetime.min.time())
        if form.status.data == "published" and not published_at:
            published_at = datetime.utcnow()

        excerpt = form.excerpt.data or content_text[:240]

        category_value = form.category.data or "general"
        normalized_cover = _normalize_drive_url(form.cover_image.data)
        image_file = request.files.get("cover_image_file")
        variants_urls: dict[str, str] = {}
        if image_file and image_file.filename:
            try:
                # Subimos las nuevas variantes primero
                variants_urls = upload_news_image_variants(
                    image_file,
                    base_name=slug_value,
                    shared_drive_id=current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID", "") or None,
                )
                # Si la subida fue exitosa y estamos editando, eliminamos las imágenes anteriores
                if post and variants_urls:
                    try:
                        delete_news_images(post.cover_image, post.image_variants)
                    except Exception as exc:
                        current_app.logger.error(f"Error eliminando imágenes previas de la noticia {post.id}: {exc}")
            except Exception as exc:  # noqa: BLE001
                current_app.logger.exception("Error generando/subiendo variantes de imagen", exc_info=exc)
                flash(
                    "No se pudieron generar ni subir las variantes en Drive. Revisa la configuración.",
                    "danger",
                )
        cover_value = variants_urls.get("latest") or normalized_cover

        if post:
            post.title = form.title.data.strip()
            post.slug = slug_value
            post.body_html = content_html
            post.excerpt = excerpt
            post.status = form.status.data
            post.tags = form.image_layout.data  # usamos tags para layout
            post.cover_image = cover_value or post.cover_image
            if variants_urls:
                post.image_variants = variants_urls
            post.published_at = published_at
            post.category = category_value
            db.session.commit()
            flash("Noticia actualizada", "success")
        else:
            post = Post(
                title=form.title.data.strip(),
                slug=slug_value,
                body_html=content_html,
                excerpt=excerpt,
                status=form.status.data,
                category=category_value,
                tags=form.image_layout.data,  # layout
                cover_image=cover_value,
                image_variants=variants_urls or None,
                author_id=current_user.id,
                published_at=published_at,
            )
            db.session.add(post)
            db.session.commit()
            flash("Noticia guardada en el tablón", "success")
        return redirect(url_for("admin.posts"))


    if request.method == "POST":
        flash("Revisa los datos del formulario de noticia.", "warning")

    return render_template("admin/posts.html", form=form, posts=recent_posts, can_edit_posts=can_edit_posts)


@admin_bp.route("/posts/featured-order", methods=["POST"])
@csrf.exempt
@login_required
def update_featured_order():
    if not current_user.has_permission("manage_posts"):
        abort(403)

    payload = request.get_json(silent=True) or {}
    raw_order = payload.get("order")
    order_ids: list[int] = []
    seen_ids: set[int] = set()
    if isinstance(raw_order, list):
        for candidate in raw_order:
            try:
                value = int(candidate)
            except (TypeError, ValueError):
                continue
            if value in seen_ids:
                continue
            seen_ids.add(value)
            order_ids.append(value)

    if order_ids:
        Post.query.filter(
            Post.featured_position.isnot(None),
            ~Post.id.in_(order_ids),
        ).update({"featured_position": None}, synchronize_session=False)
    else:
        Post.query.filter(Post.featured_position.isnot(None)).update(
            {"featured_position": None}, synchronize_session=False
        )

    relevant_posts = {
        post.id: post for post in Post.query.filter(Post.id.in_(order_ids)).all()
    }

    for index, post_id in enumerate(order_ids, start=1):
        post = relevant_posts.get(post_id)
        if post:
            post.featured_position = index

    db.session.commit()
    return jsonify({"status": "ok"}), 200


@admin_bp.route("/posts/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id: int):
    if not current_user.has_permission("manage_posts"):
        abort(403)
    post = Post.query.get_or_404(post_id)
    
    # Eliminar imágenes asociadas de Drive o local
    try:
        delete_news_images(post.cover_image, post.image_variants)
    except Exception as e:
        current_app.logger.error(f"Error eliminando imágenes de la noticia {post_id}: {e}")
    
    # Eliminar la noticia de la base de datos
    db.session.delete(post)
    db.session.commit()
    flash("Noticia eliminada", "success")
    return redirect(url_for("admin.posts"))


@admin_bp.route("/eventos", methods=["GET", "POST"])
@login_required
def admin_eventos():
    can_edit_events = current_user.has_permission("manage_events") or user_is_privileged(current_user)
    can_view_events = can_edit_events or current_user.has_permission("view_events")
    if request.method == "POST" and not can_edit_events:
        abort(403)
    if request.method == "GET" and not can_view_events:
        abort(403)

    form = EventForm()
    events = Event.query.order_by(Event.start_at.asc()).all()

    if form.validate_on_submit():
        start_at = _parse_datetime_local(form.start_at.data)
        end_at = _parse_datetime_local(form.end_at.data)
        if not start_at or not end_at:
            flash("Proporciona una fecha y hora válidas para inicio y fin.", "warning")
        elif end_at <= start_at:
            flash("La fecha de fin debe ser posterior al inicio del evento.", "warning")
        else:
            slug_value = _generate_unique_event_slug(form.title.data)
            location_value = (form.location.data or "").strip()
            if not location_value:
                location_value = None
            capacity_value = form.capacity.data
            if capacity_value is not None and capacity_value <= 0:
                capacity_value = None
            cover_raw = (form.cover_image.data or "").strip()
            cover_value = _normalize_drive_url(cover_raw) if cover_raw else None
            event = Event(
                title=form.title.data.strip(),
                slug=slug_value,
                description_html=form.description.data.strip(),
                category=form.category.data or "actividades",
                start_at=start_at,
                end_at=end_at,
                location=location_value,
                capacity=capacity_value,
                cover_image=cover_value,
                status=form.status.data,
                organizer_id=current_user.id,
            )
            db.session.add(event)
            db.session.commit()
            flash("Evento guardado correctamente.", "success")
            return redirect(url_for("admin.admin_eventos"))

    return render_template(
        "admin/eventos.html",
        form=form,
        events=events,
        category_labels=EVENT_CATEGORY_LABELS,
        can_edit_events=can_edit_events,
    )


@admin_bp.route("/comisiones")
@login_required
def commissions_index():
    can_view_commissions_admin = (
        current_user.has_permission("manage_commissions")
        or current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    )
    if not can_view_commissions_admin:
        abort(403)

    commissions = Commission.query.order_by(Commission.created_at.desc()).all()
    stats: dict[int, dict[str, object]] = {}
    now_dt = datetime.utcnow()
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

    return render_template("admin/comisiones.html", commissions=commissions, stats=stats)


@admin_bp.route("/comisiones/<int:commission_id>")
@login_required
def commission_detail(commission_id: int):
    can_view_commissions_admin = (
        current_user.has_permission("manage_commissions")
        or current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    )
    if not can_view_commissions_admin:
        abort(403)

    commission = Commission.query.get_or_404(commission_id)
    now_dt = datetime.utcnow()
    active_project_statuses = ("pendiente", "en_progreso")

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
    members_count = len(members_list)
    active_projects = (
        commission.projects.filter(CommissionProject.status.in_(active_project_statuses))
        .order_by(CommissionProject.created_at.desc())
        .all()
    )
    next_meeting = (
        commission.meetings.filter(
            CommissionMeeting.project_id.is_(None),
            CommissionMeeting.start_at >= now_dt,
        )
        .order_by(CommissionMeeting.start_at.asc())
        .first()
    )
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
    discussions = (
        Suggestion.query.filter(
            Suggestion.category == f"comision:{commission.id}",
            Suggestion.status.in_(("pendiente", "aprobada")),
        )
        .order_by(Suggestion.updated_at.desc())
        .limit(20)
        .all()
    )
    discussion_vote_counts = {}
    if discussions:
        rows = (
            db.session.query(Vote.suggestion_id, func.count(Vote.id))
            .filter(Vote.suggestion_id.in_([discussion.id for discussion in discussions]))
            .group_by(Vote.suggestion_id)
            .all()
        )
        discussion_vote_counts = {suggestion_id: count for suggestion_id, count in rows}

    can_manage_members = (
        current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    )

    can_manage_discussions = (
        current_user.has_permission("manage_suggestions")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    can_manage_projects = current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    can_manage_meetings = current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    can_edit_commission = current_user.has_permission("manage_commissions") or user_is_privileged(current_user)
    can_create_discussions = can_manage_discussions

    return render_template(
        "admin/comision_detalle.html",
        commission=commission,
        members_count=members_count,
        members_list=members_list,
        active_projects=active_projects,
        next_meeting=next_meeting,
        upcoming_meetings=upcoming_meetings,
        past_meetings=past_meetings,
        discussions=discussions,
        discussion_vote_counts=discussion_vote_counts,
        can_manage_members=can_manage_members,
        can_manage_discussions=can_manage_discussions,
        can_manage_projects=can_manage_projects,
        can_manage_meetings=can_manage_meetings,
        can_edit_commission=can_edit_commission,
        can_create_discussions=can_create_discussions,
    )


@admin_bp.route("/comisiones/nueva", methods=["GET", "POST"])
@admin_bp.route("/comisiones/<int:commission_id>/editar", methods=["GET", "POST"])
@login_required
def commission_edit(commission_id: int | None = None):
    if not (current_user.has_permission("manage_commissions") or user_is_privileged(current_user)):
        abort(403)

    commission = Commission.query.get_or_404(commission_id) if commission_id else None
    form = CommissionForm(obj=commission)
    if request.method == "GET" and commission:
        form.description.data = commission.description_html
        form.is_active.data = commission.is_active

    if form.validate_on_submit():
        if commission:
            new_name = form.name.data.strip()
            name_changed = new_name != (commission.name or "").strip()
            commission.name = new_name
            commission.description_html = form.description.data
            commission.is_active = bool(form.is_active.data)
            if not commission.slug or name_changed:
                commission.slug = _generate_unique_commission_slug(
                    new_name,
                    exclude_id=commission.id,
                )
        else:
            new_name = form.name.data.strip()
            commission = Commission(
                name=new_name,
                slug=_generate_unique_commission_slug(new_name),
                description_html=form.description.data,
                is_active=bool(form.is_active.data),
            )
            db.session.add(commission)
        db.session.commit()
        flash("Comisión guardada correctamente.", "success")
        return redirect(url_for("admin.commission_detail", commission_id=commission.id))

    return render_template("admin/comision_form.html", form=form, commission=commission)


@admin_bp.route("/comisiones/<int:commission_id>/miembros", methods=["GET", "POST"])
@login_required
def commission_members(commission_id: int):
    can_manage_members = (
        current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    )
    if not can_manage_members:
        abort(403)
    commission = Commission.query.get_or_404(commission_id)
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
            db.session.add(
                CommissionMembership(
                    commission_id=commission.id,
                    user_id=form.user_id.data,
                    role=form.role.data,
                    is_active=True,
                )
            )
        db.session.commit()
        flash("Miembro actualizado", "success")
        return redirect(url_for("admin.commission_members", commission_id=commission.id))

    return render_template(
        "admin/comision_miembros.html",
        commission=commission,
        members_active=members_active,
        members_history=members_history,
        form=form,
        header_kicker=f"Comisiones · {commission.name} - Miembros",
        back_href=url_for("admin.commission_detail", commission_id=commission.id),
        back_label="Volver a comision",
    )


@admin_bp.route("/comisiones/<int:commission_id>/miembros/<int:membership_id>/desactivar", methods=["POST"])
@login_required
def commission_member_disable_admin(commission_id: int, membership_id: int):
    if not (
        current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    ):
        abort(403)
    membership = CommissionMembership.query.filter_by(id=membership_id, commission_id=commission_id).first_or_404()
    membership.is_active = False
    db.session.commit()
    flash("Miembro desactivado", "info")
    return redirect(url_for("admin.commission_members", commission_id=commission_id))


@admin_bp.route("/comisiones/<int:commission_id>/miembros/<int:membership_id>/reactivar", methods=["POST"])
@login_required
def commission_member_reactivate_admin(commission_id: int, membership_id: int):
    if not (
        current_user.has_permission("manage_commission_members")
        or user_is_privileged(current_user)
    ):
        abort(403)
    membership = CommissionMembership.query.filter_by(id=membership_id, commission_id=commission_id).first_or_404()
    membership.is_active = True
    db.session.commit()
    flash("Miembro reactivado", "success")
    return redirect(url_for("admin.commission_members", commission_id=commission_id))


@admin_bp.route("/comisiones/<int:commission_id>/proyectos/nuevo", methods=["GET", "POST"])
@admin_bp.route("/comisiones/<int:commission_id>/proyectos/<int:project_id>/editar", methods=["GET", "POST"])
@admin_bp.route("/comisiones/<slug>/proyectos/nuevo", methods=["GET", "POST"])
@admin_bp.route("/comisiones/<slug>/proyectos/<int:project_id>/editar", methods=["GET", "POST"])
@login_required
def commission_project_edit(
    commission_id: int | None = None,
    slug: str | None = None,
    project_id: int | None = None,
):
    if not (
        current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)
    if commission_id is not None:
        commission = Commission.query.get_or_404(commission_id)
    else:
        commission = Commission.query.filter_by(slug=slug).first_or_404()
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
        return redirect(url_for("admin.commissions_index"))

    if request.method == "GET" and project:
        form.responsible_id.data = project.responsible_id or 0

    return render_template(
        "shared/comision_proyecto_form.html",
        form=form,
        commission=commission,
        project=project,
        header_kicker="Comisiones - Administracion",
        back_href=url_for("admin.commissions_index"),
        back_label="Volver",
    )


@admin_bp.route("/comisiones/<int:commission_id>/reuniones/nueva", methods=["GET", "POST"])
@admin_bp.route("/comisiones/<int:commission_id>/reuniones/<int:meeting_id>/editar", methods=["GET", "POST"])
@login_required
def commission_meeting_edit(commission_id: int, meeting_id: int | None = None):
    if not (
        current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)
    commission = Commission.query.get_or_404(commission_id)
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

    if form.validate_on_submit():
        start_at = _parse_datetime_local(form.start_at.data)
        end_at = _parse_datetime_local(form.end_at.data)
        if not start_at or not end_at or end_at <= start_at:
            flash("Revisa las fechas de inicio y fin", "warning")
            now = datetime.now()
            now_str = now.strftime("%Y-%m-%dT%H:%M")
            return render_template(
                "admin/comision_reunion_form.html",
                form=form,
                commission=commission,
                meeting=meeting,
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
        
        return redirect(url_for("admin.commissions_index"))

    # Para reuniones nuevas, asignar descripción por defecto
    if request.method == "GET" and not meeting and not form.description.data:
        form.description.data = default_description

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%dT%H:%M")

    return render_template(
        "admin/comision_reunion_form.html",
        form=form,
        commission=commission,
        meeting=meeting,
        now_str=now_str,
    )


@admin_bp.route("/permisos", methods=["GET", "POST"])
@login_required
def permissions():
    can_edit_permissions = current_user.has_permission("manage_permissions") or user_is_privileged(current_user)
    can_view_permissions = can_edit_permissions or current_user.has_permission("view_permissions")
    if not can_view_permissions:
        abort(403)

    public_only_keys = {meta["key"] for meta in PERMISSION_DEFINITIONS if meta.get("public_only")}

    def _role_is_privileged(role: Role) -> bool:
        role_name = (getattr(role, "name", "") or "").strip().lower()
        if role_name in PRIVILEGED_ROLES:
            return True
        role_ascii = unicodedata.normalize("NFKD", role_name).encode("ascii", "ignore").decode("ascii")
        return role_ascii in PRIVILEGED_ROLES

    roles, permissions_list = ensure_roles_and_permissions(DEFAULT_ROLE_NAMES)
    if not roles:
        roles = Role.query.order_by(Role.name_lookup.asc()).all()
    if not permissions_list:
        permissions_list = Permission.query.order_by(Permission.key.asc()).all()

    excluded_permission_keys = {
        "manage_commission_projects",
        "manage_commission_meetings",
        "view_all_commission_calendar",
    }
    permissions_list = [
        permission
        for permission in permissions_list
        if (getattr(permission, "key", "") or "") not in excluded_permission_keys
    ]

    role_ids = [role.id for role in roles if role.id is not None]
    permission_ids = [permission.id for permission in permissions_list if permission.id is not None]
    role_permissions = []
    if role_ids and permission_ids:
        role_permissions = (
            RolePermission.query.filter(
                RolePermission.role_id.in_(role_ids),
                RolePermission.permission_id.in_(permission_ids),
            ).all()
        )
    role_permission_map = {(rp.role_id, rp.permission_id): rp for rp in role_permissions}
    existing = {(rp.role_id, rp.permission_id): bool(rp.allowed) for rp in role_permissions}
    # Para roles privilegiados (admin/presidente/etc), la ausencia de asignación se
    # interpreta como permitido en `User.has_permission()`. Reflejamos ese "permitido"
    # implícito en la UI para que el guardado sea consistente.
    for role in roles:
        role_id = getattr(role, "id", None)
        if role_id is None or not _role_is_privileged(role):
            continue
        for permission in permissions_list:
            if (getattr(permission, "key", "") or "") in public_only_keys:
                continue
            permission_id = getattr(permission, "id", None)
            if permission_id is None:
                continue
            existing.setdefault((role_id, permission_id), True)
    grouped_permissions = group_permissions_by_section(permissions_list)
    supports_public_permissions = Permission.supports_public_flag()

    if request.method == "POST":
        if not can_edit_permissions:
            abort(403)
        changes = 0

        public_permission_ids: set[int] = set()
        is_public_by_permission_id: dict[int, bool] = {}
        if supports_public_permissions:
            for permission in permissions_list:
                permission_id = getattr(permission, "id", None)
                if permission_id is None:
                    continue
                is_public = f"public_{permission_id}" in request.form
                is_public_by_permission_id[int(permission_id)] = is_public
                if bool(getattr(permission, "is_public", False)) != is_public:
                    permission.is_public = is_public
                    changes += 1
                if is_public:
                    public_permission_ids.add(int(permission_id))

            if public_permission_ids:
                deleted = (
                    RolePermission.query.filter(RolePermission.permission_id.in_(public_permission_ids))
                    .delete(synchronize_session=False)
                )
                changes += int(deleted or 0)
        for role in roles:
            role_id = getattr(role, "id", None)
            role_is_privileged = _role_is_privileged(role)
            if role_id is None:
                continue
            for permission in permissions_list:
                if (getattr(permission, "key", "") or "") in public_only_keys:
                    continue
                permission_id = getattr(permission, "id", None)
                if permission_id is None:
                    continue
                if supports_public_permissions and is_public_by_permission_id.get(int(permission_id), False):
                    continue
                field_name = f"perm_{role_id}_{permission_id}"
                allowed = field_name in request.form
                rp_key = (role_id, permission_id)
                rp = role_permission_map.get(rp_key)
                if rp:
                    if bool(rp.allowed) != allowed:
                        rp.allowed = allowed
                        changes += 1
                else:
                    # Para roles privilegiados, solo persistimos "deny" explícitos; los "allow"
                    # implícitos se mantienen sin filas en `role_permissions`.
                    if (role_is_privileged and not allowed) or (allowed and not role_is_privileged):
                        db.session.add(
                            RolePermission(
                                role_id=role_id,
                                permission_id=permission_id,
                                allowed=allowed,
                            )
                        )
                        changes += 1
        try:
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            current_app.logger.exception("Error guardando permisos", exc_info=exc)
            flash("No se pudieron guardar los permisos", "danger")
            return redirect(url_for("admin.permissions"))
        flash("Permisos actualizados", "success" if changes else "info")
        return redirect(url_for("admin.permissions"))

    return render_template(
        "admin/permisos.html",
        roles=roles,
        permissions=permissions_list,
        existing=existing,
        grouped_permissions=grouped_permissions,
        can_edit_permissions=can_edit_permissions,
        supports_public_permissions=supports_public_permissions,
    )


@admin_bp.route("/sugerencias")
@login_required
def admin_sugerencias():
    if not (
        current_user.has_permission("manage_suggestions")
        or current_user.has_permission("view_suggestions")
        or user_is_privileged(current_user)
    ):
        abort(403)
    return render_template("admin/sugerencias.html")


@admin_bp.route("/usuarios")
@login_required
def usuarios():
    can_manage = current_user.has_permission("manage_members") or user_is_privileged(current_user)
    can_view = can_manage or current_user.has_permission("view_members")
    if not can_view:
        abort(403)

    roles = Role.query.order_by(Role.name_lookup.asc()).all()
    pending_users = (
        User.query.filter_by(registration_approved=False)
        .filter(User.deleted_at.is_(None))
        .order_by(User.created_at.desc().nullslast(), User.id.desc())
        .all()
    )
    all_users = (
        User.query.filter(User.deleted_at.is_(None))
        .order_by(User.created_at.desc().nullslast(), User.id.desc())
        .all()
    )

    deleted_users = (
        User.query.filter(User.deleted_at.isnot(None))
        .order_by(User.deleted_at.desc().nullslast(), User.id.desc())
        .all()
    )

    can_delete_permanently = current_user.has_permission("delete_members_permanently") or user_is_privileged(current_user)

    return render_template(
        "admin/usuarios.html",
        pending_users=pending_users,
        users=all_users,
        deleted_users=deleted_users,
        roles=roles,
        can_manage_members=can_manage,
        can_delete_permanently=can_delete_permanently,
    )


@admin_bp.route("/usuarios/status")
@login_required
def usuarios_status():
    """Endpoint ligero para refrescar estados en la pantalla de usuarios."""
    can_manage = current_user.has_permission("manage_members") or user_is_privileged(current_user)
    can_view = can_manage or current_user.has_permission("view_members")
    if not can_view:
        abort(403)

    raw_ids = (request.args.get("ids") or "").strip()
    if not raw_ids:
        return jsonify({"ok": True, "users": {}})

    ids: list[int] = []
    for part in raw_ids.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue

    if not ids:
        return jsonify({"ok": True, "users": {}})

    users = User.query.filter(User.id.in_(ids)).all()
    payload = {
        str(u.id): {
            "email_verified": bool(u.email_verified),
            "registration_approved": bool(u.registration_approved),
            "is_active": bool(u.is_active),
        }
        for u in users
    }
    return jsonify({"ok": True, "users": payload})


@admin_bp.route("/usuarios/pending-count")
@login_required
def usuarios_pending_count():
    """Número de usuarios con aprobación pendiente (para el badge del menú)."""
    can_manage = current_user.has_permission("manage_members") or user_is_privileged(current_user)
    can_view = can_manage or current_user.has_permission("view_members")
    if not can_view:
        abort(403)

    pending = User.query.filter_by(registration_approved=False).count()
    return jsonify({"ok": True, "pending": int(pending)})


def _require_manage_members() -> None:
    if not (current_user.has_permission("manage_members") or user_is_privileged(current_user)):
        abort(403)


@admin_bp.route("/usuarios/<int:user_id>/aprobar", methods=["POST"])
@login_required
def aprobar_usuario(user_id: int):
    _require_manage_members()
    from app.services.mail_service import send_member_approval_email

    user = User.query.get_or_404(user_id)
    if not user.email_verified:
        flash(
            "No puedes aprobar el alta hasta que el usuario verifique su correo.",
            "warning",
        )
        return redirect(url_for("admin.usuarios"))
    if not user.registration_approved:
        user.registration_approved = True
        user.approved_at = datetime.utcnow()
        user.approved_by_id = current_user.id
        db.session.commit()

    result = send_member_approval_email(
        recipient_email=user.email,
        app_config=current_app.config,
    )
    if result.get("ok"):
        flash("Alta aprobada. Se ha enviado el correo de bienvenida.", "success")
    else:
        flash(
            "Alta aprobada, pero no se pudo enviar el correo de bienvenida. Puedes reenviarlo desde esta pantalla.",
            "warning",
        )
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/rol", methods=["POST"])
@login_required
def cambiar_rol_usuario(user_id: int):
    _require_manage_members()
    role_id = request.form.get("role_id", type=int)
    if not role_id:
        flash("Rol inválido.", "warning")
        return redirect(url_for("admin.usuarios"))

    role = Role.query.get(role_id)
    if not role:
        flash("Rol no encontrado.", "warning")
        return redirect(url_for("admin.usuarios"))

    user = User.query.get_or_404(user_id)
    user.role_id = role.id
    db.session.commit()
    flash("Rol actualizado.", "success")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/estado", methods=["POST"])
@login_required
def cambiar_estado_usuario(user_id: int):
    _require_manage_members()
    is_active = request.form.get("is_active") == "1"
    if int(user_id) == int(current_user.id) and not is_active:
        flash("No puedes desactivar tu propia cuenta.", "warning")
        return redirect(url_for("admin.usuarios"))

    user = User.query.get_or_404(user_id)
    if is_active and not user.email_verified:
        flash(
            "No puedes activar la cuenta hasta que el usuario verifique su correo.",
            "warning",
        )
        return redirect(url_for("admin.usuarios"))
    old_status = user.is_active
    user.is_active = bool(is_active)

    if old_status and not user.is_active:
        # Deactivating
        user.deactivated_at = datetime.utcnow()
        send_member_deactivation_email(
            recipient_email=user.email,
            app_config=current_app.config
        )
    elif not old_status and user.is_active:
        # Reactivating
        user.deactivated_at = None
        send_member_reactivation_email(
            recipient_email=user.email,
            app_config=current_app.config
        )

    db.session.commit()
    flash("Estado actualizado.", "success")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/eliminar", methods=["POST"])
@login_required
def eliminar_usuario(user_id: int):
    _require_manage_members()

    if int(user_id) == int(current_user.id):
        flash("No puedes eliminar tu propia cuenta.", "warning")
        return redirect(url_for("admin.usuarios"))

    user = User.query.get_or_404(user_id)
    if getattr(user, "deleted_at", None):
        flash("El socio ya est\xE1 marcado como eliminado.", "info")
        return redirect(url_for("admin.usuarios"))
    if user.is_active:
        flash("Solo puedes eliminar un socio cuando est\xE1 desactivado.", "warning")
        return redirect(url_for("admin.usuarios"))

    if user_is_privileged(user):
        flash("No se puede eliminar una cuenta privilegiada.", "danger")
        return redirect(url_for("admin.usuarios"))

    try:
        user.deleted_at = datetime.utcnow()
        user.is_active = False
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(
            "No se pudo marcar el socio como eliminado.",
            "danger",
        )
        return redirect(url_for("admin.usuarios"))
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Error eliminando usuario", exc_info=exc)
        flash("No se pudo marcar el socio como eliminado.", "danger")
        return redirect(url_for("admin.usuarios"))

    flash("Socio marcado como eliminado.", "success")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/eliminar-permanente", methods=["POST"])
@login_required
def eliminar_permanente_usuario(user_id: int):
    if not (current_user.has_permission("delete_members_permanently") or user_is_privileged(current_user)):
        abort(403)

    if int(user_id) == int(current_user.id):
        flash("No puedes eliminar tu propia cuenta.", "warning")
        return redirect(url_for("admin.usuarios"))

    user = User.query.get_or_404(user_id)

    if not user.deleted_at:
        flash(
            "Solo se pueden eliminar permanentemente socios que ya han sido marcados como eliminados.",
            "warning",
        )
        return redirect(url_for("admin.usuarios"))

    if user_is_privileged(user):
        flash("No se puede eliminar permanentemente una cuenta privilegiada.", "danger")
        return redirect(url_for("admin.usuarios"))

    try:
        # Antes de borrar, desvinculamos de aprobaciones y proyectos para evitar errores de FK si no hay cascade
        User.query.filter_by(approved_by_id=user.id).update({User.approved_by_id: None})
        CommissionProject.query.filter_by(responsible_id=user.id).update({CommissionProject.responsible_id: None})

        db.session.delete(user)
        db.session.commit()
        flash(
            f"El usuario {user.display_name} ha sido eliminado permanentemente de la base de datos.",
            "success",
        )
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Error eliminando permanentemente usuario", exc_info=exc)
        flash("Error al intentar eliminar permanentemente al usuario.", "danger")

    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/reenviar-set-password", methods=["POST"])
@login_required
def reenviar_set_password(user_id: int):
    _require_manage_members()
    from app.services.mail_service import send_set_password_email
    from app.utils import generate_set_password_token

    user = User.query.get_or_404(user_id)
    if not user.email_verified:
        flash("El usuario aún no ha verificado su correo.", "warning")
        return redirect(url_for("admin.usuarios"))
    if not user.registration_approved:
        flash("La cuenta aún no está aprobada.", "warning")
        return redirect(url_for("admin.usuarios"))

    token = generate_set_password_token(user.id, user.password_hash)
    set_password_url = url_for("public.set_password", token=token, _external=True)
    result = send_set_password_email(
        recipient_email=user.email,
        set_password_url=set_password_url,
        app_config=current_app.config,
    )
    if result.get("ok"):
        flash("Enlace enviado.", "success")
    else:
        flash("No se pudo enviar el correo.", "danger")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/datos", methods=["POST"])
@login_required
def actualizar_datos_usuario(user_id: int):
    _require_manage_members()

    user = User.query.get_or_404(user_id)

    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    phone_number = (request.form.get("phone_number") or "").strip()
    role_id = request.form.get("role_id", type=int)

    errors: list[str] = []
    if not (2 <= len(first_name) <= 64):
        errors.append("El nombre debe tener entre 2 y 64 caracteres.")
    if not (2 <= len(last_name) <= 64):
        errors.append("Los apellidos deben tener entre 2 y 64 caracteres.")
    if phone_number and not (6 <= len(phone_number) <= 32):
        errors.append("El teléfono debe tener entre 6 y 32 caracteres.")
    if role_id:
        role = Role.query.get(role_id)
        if not role:
            errors.append("Rol no encontrado.")

    if errors:
        for message in errors:
            flash(message, "warning")
        return redirect(url_for("admin.usuarios"))

    user.first_name = first_name
    user.last_name = last_name
    user.phone_number = phone_number or None
    if role_id:
        user.role_id = role_id
    db.session.commit()
    flash("Datos de usuario actualizados.", "success")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/reenviar-verificacion", methods=["POST"])
@login_required
def reenviar_verificacion_usuario(user_id: int):
    _require_manage_members()
    from app.services.mail_service import send_member_verification_email
    from app.utils import generate_email_verification_token

    user = User.query.get_or_404(user_id)
    if not user.is_active:
        flash("La cuenta está desactivada.", "warning")
        return redirect(url_for("admin.usuarios"))
    if user.email_verified:
        flash("El correo ya está verificado.", "info")
        return redirect(url_for("admin.usuarios"))

    token = generate_email_verification_token(user.id, user.email_lookup)
    verify_url = url_for("public.verify_email", token=token, _external=True)
    result = send_member_verification_email(
        recipient_email=user.email,
        verify_url=verify_url,
        app_config=current_app.config,
    )
    if result.get("ok"):
        flash("Se ha enviado el enlace de verificación al usuario.", "success")
    else:
        flash("No se pudo enviar el correo de verificación.", "danger")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/email", methods=["POST"])
@login_required
def actualizar_email_usuario(user_id: int):
    _require_manage_members()
    from app.services.mail_service import send_member_verification_email
    from app.utils import generate_email_verification_token

    user = User.query.get_or_404(user_id)
    raw_email = (request.form.get("email") or "").strip()
    current_email = (user.email or "").strip().lower()

    if not raw_email:
        flash("El correo es obligatorio.", "warning")
        return redirect(url_for("admin.usuarios"))

    if len(raw_email) > 256:
        flash("Correo inválido.", "warning")
        return redirect(url_for("admin.usuarios"))

    try:
        new_email = validate_email(raw_email, check_deliverability=False).email
    except EmailNotValidError:
        flash("Correo inválido.", "warning")
        return redirect(url_for("admin.usuarios"))

    if new_email.strip().lower() == current_email:
        flash("No hay cambios en el correo.", "info")
        return redirect(url_for("admin.usuarios"))

    lookup_email = make_lookup_hash(new_email)
    existing = User.query.filter_by(email_lookup=lookup_email).first()
    if existing and int(existing.id) != int(user.id):
        flash("Ya existe una cuenta con ese correo.", "warning")
        return redirect(url_for("admin.usuarios"))

    user.email = new_email
    if current_email and (user.username or "").strip().lower() == current_email:
        user.username = new_email
    user.email_verified = False

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("No se pudo cambiar el correo (ya existe o datos inválidos).", "danger")
        return redirect(url_for("admin.usuarios"))

    token = generate_email_verification_token(user.id, user.email_lookup)
    verify_url = url_for("public.verify_email", token=token, _external=True)
    result = send_member_verification_email(
        recipient_email=user.email,
        verify_url=verify_url,
        app_config=current_app.config,
    )
    if result.get("ok"):
        flash("Correo actualizado. Se ha enviado un enlace de verificación al nuevo correo.", "success")
    else:
        flash(
            "Correo actualizado, pero no se pudo enviar el correo de verificación. Puedes reenviarlo desde el modal.",
            "warning",
        )
    return redirect(url_for("admin.usuarios"))


# ============== Personalización de la Web ==============

def _require_view_styles():
    """Verifica que el usuario tenga permisos para ver la sección de estilos."""
    if not (current_user.has_permission("view_styles") or current_user.has_permission("manage_styles") or user_is_privileged(current_user)):
        abort(403)


def _require_manage_styles():
    """Verifica que el usuario tenga permisos para gestionar estilos."""
    if not (current_user.has_permission("manage_styles") or user_is_privileged(current_user)):
        abort(403)


@admin_bp.route("/personalizacion")
@login_required
def personalizacion():
    """Vista principal de personalización de estilos."""
    _require_view_styles()
    
    from app.services.style_service import list_styles, get_style_calendar_color
    
    styles = list_styles()
    for style in styles:
        style["calendar_color"] = get_style_calendar_color(style.get("name"))
    return render_template("admin/personalizacion.html", styles=styles)


@admin_bp.route("/personalizacion/programacion", methods=["GET", "POST"])
@login_required
def style_schedule():
    """Gestiona la programación de estilos."""
    _require_manage_styles()
    
    from app.services.style_service import (
        list_styles, 
        list_style_schedules, 
        add_style_schedule
    )
    from datetime import datetime
    
    if request.method == "POST":
        current_app.logger.info(f"POST /personalizacion/programacion - Form: {request.form}")
        style_name = request.form.get("style_name")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            
            if start_date > end_date:
                flash("La fecha de inicio no puede ser posterior a la de fin.", "danger")
            else:
                ok, msg = add_style_schedule(style_name, start_date, end_date)
                if ok:
                    flash(msg, "success")
                else:
                    flash(msg, "danger")
        except ValueError:
            flash("Formato de fecha inválido.", "danger")
            
        return redirect(url_for("admin.style_schedule"))
    
    styles = list_styles()
    schedules = list_style_schedules()
    return render_template(
        "admin/style_schedule.html", 
        styles=styles, 
        schedules=schedules,
        today=datetime.now().date()
    )


@admin_bp.route("/personalizacion/programacion/eliminar/<int:schedule_id>", methods=["POST"])
@login_required
def style_schedule_delete(schedule_id: int):
    """Elimina una programación de estilo."""
    _require_manage_styles()
    
    from app.services.style_service import delete_style_schedule
    
    if delete_style_schedule(schedule_id):
        flash("Programación eliminada.", "success")
    else:
        flash("Error al eliminar la programación.", "danger")
        
    return redirect(url_for("admin.style_schedule"))


@admin_bp.route("/personalizacion/api/styles-catalog", methods=["GET"])
@login_required
def api_styles_catalog():
    """Devuelve estilos disponibles (Drive + General) con logo 64x64 y color de calendario."""
    _require_manage_styles()

    from app.services.style_service import list_styles, get_style_calendar_colors
    from urllib.parse import quote

    styles = list_styles()
    colors = get_style_calendar_colors()
    catalog = []
    for s in styles:
        name = s.get("name") if isinstance(s, dict) else getattr(s, "name", None)
        if not name:
            continue
        catalog.append(
            {
                "name": name,
                "logo_url": f"/style/{quote(str(name))}/Logo_AMPA_64x64.png",
                "color": colors.get(name),
            }
        )
    return jsonify({"ok": True, "styles": catalog, "colors": colors})


@admin_bp.route("/personalizacion/api/style/<style_name>/calendar-color", methods=["GET", "POST"])
@login_required
def api_style_calendar_color(style_name: str):
    """Lee/guarda el color de calendario para un estilo."""
    _require_manage_styles()

    from app.services.style_service import get_style_calendar_color, set_style_calendar_color

    if request.method == "GET":
        return jsonify({"ok": True, "style_name": style_name, "color": get_style_calendar_color(style_name)})

    data = request.get_json(silent=True) or {}
    color = data.get("color")
    if not set_style_calendar_color(style_name, color):
        return jsonify({"ok": False, "error": "Color inválido"}), 400
    return jsonify({"ok": True})


@admin_bp.route("/personalizacion/api/style-schedules", methods=["GET"])
@login_required
def api_style_schedules_range():
    """Lista programaciones que intersectan un rango (para pintar el calendario)."""
    _require_manage_styles()

    from datetime import datetime
    from app.services.style_service import list_style_schedules_between, get_style_calendar_colors

    start_str = request.args.get("from")
    end_str = request.args.get("to")
    if not start_str or not end_str:
        return jsonify({"ok": False, "error": "Parámetros 'from' y 'to' requeridos"}), 400

    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"ok": False, "error": "Formato de fecha inválido"}), 400

    schedules = list_style_schedules_between(start_date, end_date)
    return jsonify({"ok": True, "schedules": schedules, "colors": get_style_calendar_colors()})


@admin_bp.route("/personalizacion/api/style-schedules/apply", methods=["POST"])
@login_required
def api_style_schedules_apply():
    """Aplica un estilo a una selección de días con manejo de solapes."""
    _require_manage_styles()

    data = request.get_json(silent=True) or {}
    style_name = data.get("style_name")
    dates = data.get("dates") or []
    mode = data.get("mode")  # None | overwrite | keep

    from app.services.style_service import apply_style_schedule_days

    result = apply_style_schedule_days(style_name, dates, mode=mode)
    if result.get("conflict"):
        return jsonify(result), 409
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)


@admin_bp.route("/personalizacion/api/style-schedules/clear", methods=["POST"])
@login_required
def api_style_schedules_clear():
    """Elimina asignaciones en una selección de días (vuelven a General por defecto)."""
    _require_manage_styles()

    data = request.get_json(silent=True) or {}
    dates = data.get("dates") or []

    from app.services.style_service import clear_style_schedule_days

    result = clear_style_schedule_days(dates)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)


@admin_bp.route("/personalizacion/crear", methods=["POST"])
@login_required
def style_create():
    """Crea un nuevo estilo."""
    _require_manage_styles()
    
    from app.services.style_service import create_style, duplicate_style, _sanitize_style_name
    
    name = request.form.get("name", "").strip()
    copy_from = request.form.get("copy_from", "").strip()
    
    sanitized = _sanitize_style_name(name)
    if not sanitized:
        flash("Nombre de estilo inválido.", "danger")
        return redirect(url_for("admin.personalizacion"))
    
    if copy_from:
        if duplicate_style(copy_from, sanitized):
            flash(f"Estilo '{sanitized}' creado desde '{copy_from}'.", "success")
        else:
            flash("Error al duplicar el estilo.", "danger")
    else:
        if create_style(sanitized):
            flash(f"Estilo '{sanitized}' creado.", "success")
        else:
            flash("Error al crear el estilo (puede que ya exista).", "danger")
    
    return redirect(url_for("admin.personalizacion"))


@admin_bp.route("/personalizacion/api/style/<style_name>/activate", methods=["POST"])
@login_required
def api_style_activate(style_name: str):
    """Activa un estilo."""
    _require_manage_styles()
    
    from app.services.style_service import set_active_style, style_exists
    
    if not style_exists(style_name):
        return jsonify({"ok": False, "error": "Estilo no encontrado"}), 404
    
    if set_active_style(style_name):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Error activando estilo"}), 500


@admin_bp.route("/personalizacion/api/style/<style_name>/files")
@login_required
def api_style_files(style_name: str):
    """Lista los archivos de un estilo."""
    _require_view_styles()
    
    from app.services.style_service import get_style_files
    
    files = get_style_files(style_name)
    return jsonify({"ok": True, "files": files})


@admin_bp.route("/personalizacion/api/style/<style_name>/css", methods=["GET"])
@login_required
def api_style_css_get(style_name: str):
    """Obtiene el CSS de un estilo."""
    _require_view_styles()
    
    from app.services.style_service import get_style_css_content
    
    css = get_style_css_content(style_name, with_fallback=False)
    if css is None:
        return jsonify({
            "ok": False, 
            "error": "No se pudo cargar el CSS desde Drive. Reintenta en unos segundos.",
            "css": ""
        }), 503
    return jsonify({"ok": True, "css": css})


@admin_bp.route("/personalizacion/api/style/<style_name>/css", methods=["POST"])
@login_required
def api_style_css_save(style_name: str):
    """Guarda el CSS de un estilo."""
    _require_manage_styles()
    
    from app.services.style_service import save_style_css_content
    
    data = request.get_json()
    css = data.get("css", "")
    
    if save_style_css_content(style_name, css):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Error guardando CSS"}), 500


@admin_bp.route("/personalizacion/api/style/<style_name>/upload", methods=["POST"])
@login_required
def api_style_upload(style_name: str):
    """Sube un archivo a un estilo."""
    _require_manage_styles()
    
    from app.services.style_service import upload_style_file
    
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No se recibió archivo"}), 400
    
    file = request.files["file"]
    if not file.filename:
        return jsonify({"ok": False, "error": "Nombre de archivo vacío"}), 400
    
    # Validar extensión
    allowed = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css"}
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed:
        return jsonify({"ok": False, "error": f"Extensión no permitida: {ext}"}), 400
    
    content = file.read()
    if len(content) > 5 * 1024 * 1024:  # 5MB max
        return jsonify({"ok": False, "error": "Archivo demasiado grande (max 5MB)"}), 400
    
    if upload_style_file(style_name, file.filename, content):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Error subiendo archivo"}), 500


@admin_bp.route("/personalizacion/api/style/<style_name>/slot/<path:slot_name>", methods=["POST"])
@login_required
def api_style_slot_upload(style_name: str, slot_name: str):
    """Reemplaza una imagen de un slot fijo (con reescalado/recorte)."""
    _require_manage_styles()

    from app.services.style_service import (
        STYLE_DROPPABLE_SLOTS,
        prepare_style_slot_upload,
        upload_style_file,
        invalidate_style_cache,
    )

    if slot_name not in STYLE_DROPPABLE_SLOTS:
        return jsonify({"ok": False, "error": "Slot no permitido"}), 400

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No se recibió archivo"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"ok": False, "error": "Nombre de archivo vacío"}), 400

    allowed = {".png", ".jpg", ".jpeg", ".webp"}
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed:
        return jsonify({"ok": False, "error": f"Extensión no permitida: {ext}"}), 400

    content = file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB max
        return jsonify({"ok": False, "error": "Archivo demasiado grande (max 10MB)"}), 400

    try:
        outputs = prepare_style_slot_upload(slot_name, content)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    for target_name, out_bytes, mime in outputs:
        ok = upload_style_file(style_name, target_name, out_bytes, mime)
        if not ok:
            return jsonify({"ok": False, "error": f"Error subiendo {target_name}"}), 500

    # Invalida caché del estilo para que se refresque al instante
    try:
        invalidate_style_cache(style_name)
    except Exception:
        pass

    return jsonify({"ok": True, "files": [name for name, *_ in outputs]})


@admin_bp.route("/personalizacion/api/style/<style_name>/file/<filename>", methods=["DELETE"])
@login_required
def api_style_file_delete(style_name: str, filename: str):
    """Elimina un archivo de un estilo."""
    _require_manage_styles()
    
    from app.services.style_service import delete_style_file
    
    if delete_style_file(style_name, filename):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Error eliminando archivo"}), 500


@admin_bp.route("/personalizacion/api/style/<style_name>/duplicate", methods=["POST"])
@login_required
def api_style_duplicate(style_name: str):
    """Duplica un estilo."""
    _require_manage_styles()
    
    from app.services.style_service import duplicate_style, _sanitize_style_name
    
    data = request.get_json()
    new_name = _sanitize_style_name(data.get("new_name", ""))
    
    if not new_name:
        return jsonify({"ok": False, "error": "Nombre inválido"}), 400
    
    if duplicate_style(style_name, new_name):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Error duplicando estilo"}), 500


@admin_bp.route("/personalizacion/api/style/<style_name>", methods=["DELETE"])
@login_required
def api_style_delete(style_name: str):
    """Elimina un estilo."""
    _require_manage_styles()
    
    from app.services.style_service import delete_style
    
    if style_name.lower() in ["general"]:
        return jsonify({"ok": False, "error": "No se puede eliminar el estilo General"}), 400
    
    if delete_style(style_name):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Error eliminando estilo"}), 500


@admin_bp.route("/personalizacion/api/initialize", methods=["POST"])
@login_required
def api_styles_initialize():
    """Inicializa los estilos por defecto en Drive."""
    _require_manage_styles()
    
    from app.services.style_service import initialize_default_styles
    
    try:
        results = initialize_default_styles()
        return jsonify({"ok": True, "results": results})
    except Exception as e:
        current_app.logger.error(f"Error inicializando estilos: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
