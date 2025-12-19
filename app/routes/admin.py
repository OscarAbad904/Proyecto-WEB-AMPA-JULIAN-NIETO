from flask import Blueprint, render_template, request, flash, redirect, url_for, abort, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime
import re
import unicodedata
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
from app.forms import (
    PostForm,
    EventForm,
    CommissionForm,
    CommissionMemberForm,
    CommissionProjectForm,
    CommissionMeetingForm,
    EVENT_CATEGORY_LABELS,
)
from app.utils import slugify, _normalize_drive_url, _parse_datetime_local, make_lookup_hash
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
                variants_urls = upload_news_image_variants(
                    image_file,
                    base_name=slug_value,
                    shared_drive_id=current_app.config.get("GOOGLE_DRIVE_SHARED_DRIVE_ID", "") or None,
                )
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
        or current_user.has_permission("view_commissions")
        or user_is_privileged(current_user)
    )
    if not can_view_commissions_admin:
        abort(403)

    commissions = Commission.query.order_by(Commission.created_at.desc()).all()
    stats = {}
    now_dt = datetime.utcnow()
    for commission in commissions:
        stats[commission.id] = {
            "miembros": commission.memberships.filter_by(is_active=True).count(),
            "proyectos": commission.projects.count(),
            "proximas_reuniones": commission.meetings.filter(CommissionMeeting.start_at >= now_dt).count(),
        }

    return render_template("admin/comisiones.html", commissions=commissions, stats=stats)


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
            commission.name = form.name.data.strip()
            commission.description_html = form.description.data
            commission.is_active = bool(form.is_active.data)
            if not commission.slug:
                commission.slug = _generate_unique_commission_slug(commission.name)
        else:
            commission = Commission(
                name=form.name.data.strip(),
                slug=_generate_unique_commission_slug(form.name.data),
                description_html=form.description.data,
                is_active=bool(form.is_active.data),
            )
            db.session.add(commission)
        db.session.commit()
        flash("Comisión guardada correctamente.", "success")
        return redirect(url_for("admin.commissions_index"))

    return render_template("admin/comision_form.html", form=form, commission=commission)


@admin_bp.route("/comisiones/<int:commission_id>/miembros", methods=["GET", "POST"])
@login_required
def commission_members(commission_id: int):
    can_manage_members = (
        current_user.has_permission("manage_commission_members")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    )
    if not can_manage_members:
        abort(403)
    commission = Commission.query.get_or_404(commission_id)
    form = CommissionMemberForm()
    form.user_id.choices = [(u.id, u.username) for u in User.query.filter_by(is_active=True).order_by(User.username.asc())]
    members = commission.memberships.order_by(CommissionMembership.created_at.desc()).all()

    if form.validate_on_submit():
        existing = CommissionMembership.query.filter_by(
            commission_id=commission.id, user_id=form.user_id.data
        ).first()
        if existing:
            existing.role = form.role.data
            existing.is_active = form.is_active.data
        else:
            db.session.add(
                CommissionMembership(
                    commission_id=commission.id,
                    user_id=form.user_id.data,
                    role=form.role.data,
                    is_active=form.is_active.data,
                )
            )
        db.session.commit()
        flash("Miembro actualizado", "success")
        return redirect(url_for("admin.commission_members", commission_id=commission.id))

    return render_template(
        "admin/comision_miembros.html",
        commission=commission,
        members=members,
        form=form,
    )


@admin_bp.route("/comisiones/<int:commission_id>/miembros/<int:membership_id>/desactivar", methods=["POST"])
@login_required
def commission_member_disable_admin(commission_id: int, membership_id: int):
    if not (
        current_user.has_permission("manage_commission_members")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)
    membership = CommissionMembership.query.filter_by(id=membership_id, commission_id=commission_id).first_or_404()
    membership.is_active = False
    db.session.commit()
    flash("Miembro desactivado", "info")
    return redirect(url_for("admin.commission_members", commission_id=commission_id))


@admin_bp.route("/comisiones/<int:commission_id>/proyectos/nuevo", methods=["GET", "POST"])
@admin_bp.route("/comisiones/<int:commission_id>/proyectos/<int:project_id>/editar", methods=["GET", "POST"])
@login_required
def commission_project_edit(commission_id: int, project_id: int | None = None):
    if not (
        current_user.has_permission("manage_commission_projects")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)
    commission = Commission.query.get_or_404(commission_id)
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
        return redirect(url_for("admin.commissions_index"))

    if request.method == "GET" and project:
        form.responsible_id.data = project.responsible_id or 0

    return render_template(
        "admin/comision_proyecto_form.html",
        form=form,
        commission=commission,
        project=project,
    )


@admin_bp.route("/comisiones/<int:commission_id>/reuniones/nueva", methods=["GET", "POST"])
@admin_bp.route("/comisiones/<int:commission_id>/reuniones/<int:meeting_id>/editar", methods=["GET", "POST"])
@login_required
def commission_meeting_edit(commission_id: int, meeting_id: int | None = None):
    if not (
        current_user.has_permission("manage_commission_meetings")
        or current_user.has_permission("manage_commissions")
        or user_is_privileged(current_user)
    ):
        abort(403)
    commission = Commission.query.get_or_404(commission_id)
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
            flash("Revisa las fechas de inicio y fin", "warning")
            return render_template(
                "admin/comision_reunion_form.html",
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
        flash("Reunion guardada", "success")
        return redirect(url_for("admin.commissions_index"))

    if request.method == "GET" and meeting:
        form.minutes_document_id.data = meeting.minutes_document_id or 0
        form.start_at.data = meeting.start_at.strftime("%Y-%m-%dT%H:%M")
        form.end_at.data = meeting.end_at.strftime("%Y-%m-%dT%H:%M")

    return render_template(
        "admin/comision_reunion_form.html",
        form=form,
        commission=commission,
        meeting=meeting,
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
        .order_by(User.created_at.desc().nullslast(), User.id.desc())
        .all()
    )
    all_users = User.query.order_by(User.created_at.desc().nullslast(), User.id.desc()).all()

    return render_template(
        "admin/usuarios.html",
        pending_users=pending_users,
        users=all_users,
        roles=roles,
        can_manage_members=can_manage,
    )


def _require_manage_members() -> None:
    if not (current_user.has_permission("manage_members") or user_is_privileged(current_user)):
        abort(403)


@admin_bp.route("/usuarios/<int:user_id>/aprobar", methods=["POST"])
@login_required
def aprobar_usuario(user_id: int):
    _require_manage_members()
    from app.services.mail_service import send_member_approval_email

    user = User.query.get_or_404(user_id)
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
    if user.is_active:
        flash("Solo puedes eliminar un socio cuando est\xE1 desactivado.", "warning")
        return redirect(url_for("admin.usuarios"))

    if user_is_privileged(user):
        flash("No se puede eliminar una cuenta privilegiada.", "danger")
        return redirect(url_for("admin.usuarios"))

    blockers: list[str] = []
    if user.posts.count():
        blockers.append("publicaciones")
    if user.events.count():
        blockers.append("eventos")
    if user.documents.count():
        blockers.append("documentos")
    if user.media.count():
        blockers.append("archivos")
    if blockers:
        flash(
            "No se puede eliminar porque el usuario tiene contenido asociado: "
            + ", ".join(blockers)
            + ".",
            "warning",
        )
        return redirect(url_for("admin.usuarios"))

    try:
        User.query.filter_by(approved_by_id=user.id).update(
            {User.approved_by_id: None}, synchronize_session=False
        )
        CommissionProject.query.filter_by(responsible_id=user.id).update(
            {CommissionProject.responsible_id: None}, synchronize_session=False
        )

        Enrollment.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        Membership.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        CommissionMembership.query.filter_by(user_id=user.id).delete(synchronize_session=False)

        suggestion_ids = [
            suggestion_id
            for (suggestion_id,) in db.session.query(Suggestion.id)
            .filter_by(created_by=user.id)
            .all()
        ]
        if suggestion_ids:
            Vote.query.filter(Vote.suggestion_id.in_(suggestion_ids)).delete(
                synchronize_session=False
            )
            Comment.query.filter(Comment.suggestion_id.in_(suggestion_ids)).update(
                {Comment.parent_id: None}, synchronize_session=False
            )
            Comment.query.filter(Comment.suggestion_id.in_(suggestion_ids)).delete(
                synchronize_session=False
            )
            Suggestion.query.filter(Suggestion.id.in_(suggestion_ids)).delete(
                synchronize_session=False
            )

        Vote.query.filter_by(user_id=user.id).delete(synchronize_session=False)

        comment_ids = [
            comment_id
            for (comment_id,) in db.session.query(Comment.id).filter_by(created_by=user.id).all()
        ]
        if comment_ids:
            Comment.query.filter(Comment.parent_id.in_(comment_ids)).update(
                {Comment.parent_id: None}, synchronize_session=False
            )
            Comment.query.filter(Comment.id.in_(comment_ids)).delete(synchronize_session=False)

        db.session.delete(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash(
            "No se pudo eliminar el socio (tiene datos asociados que deben eliminarse antes).",
            "danger",
        )
        return redirect(url_for("admin.usuarios"))
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.exception("Error eliminando usuario", exc_info=exc)
        flash("No se pudo eliminar el socio.", "danger")
        return redirect(url_for("admin.usuarios"))

    flash("Socio eliminado.", "success")
    return redirect(url_for("admin.usuarios"))


@admin_bp.route("/usuarios/<int:user_id>/reenviar-set-password", methods=["POST"])
@login_required
def reenviar_set_password(user_id: int):
    _require_manage_members()
    from app.services.mail_service import send_set_password_email
    from app.utils import generate_set_password_token

    user = User.query.get_or_404(user_id)
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

    errors: list[str] = []
    if not (2 <= len(first_name) <= 64):
        errors.append("El nombre debe tener entre 2 y 64 caracteres.")
    if not (2 <= len(last_name) <= 64):
        errors.append("Los apellidos deben tener entre 2 y 64 caracteres.")
    if phone_number and not (6 <= len(phone_number) <= 32):
        errors.append("El teléfono debe tener entre 6 y 32 caracteres.")

    if errors:
        for message in errors:
            flash(message, "warning")
        return redirect(url_for("admin.usuarios"))

    user.first_name = first_name
    user.last_name = last_name
    user.phone_number = phone_number or None
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
