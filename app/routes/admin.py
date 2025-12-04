from flask import Blueprint, render_template, request, flash, redirect, url_for, abort, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime
import re

from app.extensions import db, csrf
from app.models import Post, Event, user_is_privileged, _generate_unique_event_slug
from app.forms import PostForm, EventForm, EVENT_CATEGORY_LABELS
from app.utils import slugify, _normalize_drive_url, _parse_datetime_local
from app.media_utils import upload_news_image_variants, delete_news_images

admin_bp = Blueprint("admin", __name__, template_folder="../../templates/admin")


@admin_bp.route("/")
@login_required
def dashboard_admin():
    return render_template("admin/dashboard.html")


@admin_bp.route("/posts", methods=["GET", "POST"])
@login_required
def posts():
    if not user_is_privileged(current_user):
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
                    parent_folder_id=current_app.config.get("GOOGLE_DRIVE_NEWS_FOLDER_ID", "") or None,
                    folder_name=current_app.config.get("GOOGLE_DRIVE_NEWS_FOLDER_NAME", "Noticias"),
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

    return render_template("admin/posts.html", form=form, posts=recent_posts)


@admin_bp.route("/posts/featured-order", methods=["POST"])
@csrf.exempt
@login_required
def update_featured_order():
    if not user_is_privileged(current_user):
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
    if not user_is_privileged(current_user):
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
    if not user_is_privileged(current_user):
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
    )


@admin_bp.route("/sugerencias")
@login_required
def admin_sugerencias():
    return render_template("admin/sugerencias.html")


@admin_bp.route("/usuarios")
@login_required
def usuarios():
    return render_template("admin/usuarios.html")
