from flask import Blueprint, render_template, request, current_app, flash, redirect, url_for, abort
from flask_login import current_user, login_required
import re
from app.models import Post, user_is_privileged
from app.utils import _normalize_drive_url

public_bp = Blueprint("public", __name__, template_folder="../../templates/public")

def _can_view_posts() -> bool:
    return current_user.is_authenticated and (
        current_user.has_permission("manage_posts")
        or current_user.has_permission("view_posts")
        or user_is_privileged(current_user)
    )


def _can_view_events() -> bool:
    return current_user.is_authenticated and (
        current_user.has_permission("manage_events")
        or current_user.has_permission("view_events")
        or user_is_privileged(current_user)
    )


def _normalize_post_images(post: Post) -> Post:
    """Ensure cover and modal images point to a renderable URL."""
    normalized_cover = _normalize_drive_url(post.cover_image)
    variants = post.image_variants or {}
    if isinstance(variants, dict):
        post.cover_image = (
            variants.get("latest")
            or variants.get("last_v")
            or variants.get("last_h")
            or normalized_cover
        )
        post.modal_image = (
            variants.get("modal")
            or variants.get("modal_v")
            or variants.get("modal_h")
            or post.cover_image
        )
    else:
        post.cover_image = normalized_cover
        post.modal_image = normalized_cover
    return post


def _get_latest_three_posts() -> list[Post]:
    posts = (
        Post.query.filter_by(status="published")
        .order_by(Post.published_at.desc().nullslast(), Post.created_at.desc())
        .limit(3)
        .all()
    )
    posts = [_normalize_post_images(post) for post in posts]

    posts_with_position = [p for p in posts if p.featured_position is not None]
    posts_without_position = [p for p in posts if p.featured_position is None]
    posts_with_position.sort(key=lambda p: p.featured_position or 0)

    return posts_with_position + posts_without_position

@public_bp.route("/")
@public_bp.route("/AMPA")
def home():
    latest_three = _get_latest_three_posts() if _can_view_posts() else []
    return render_template("index.html", latest_three=latest_three)


@public_bp.route("/quienes-somos")
def quienes_somos():
    return render_template("public/quienes_somos.html")


@public_bp.route("/noticias")
@login_required
def noticias():
    if not _can_view_posts():
        abort(403)
    query = request.args.get("q", "")
    posts = (
        Post.query.filter_by(status="published")
        .order_by(Post.published_at.desc().nullslast(), Post.created_at.desc())
        .all()
    )
    posts = [_normalize_post_images(post) for post in posts]

    # Siempre obtener las 3 noticias m?s recientes (por published_at descendente)
    latest_three = _get_latest_three_posts()
    return render_template("public/noticias.html", query=query, posts=posts, latest_three=latest_three)

@public_bp.route("/noticias/<slug>")
@login_required
def noticia_detalle(slug):
    if not _can_view_posts():
        abort(403)
    return render_template("public/noticia_detalle.html", slug=slug)


@public_bp.route("/eventos")
@login_required
def eventos():
    if not _can_view_events():
        abort(403)
    return render_template("public/eventos.html")


@public_bp.route("/calendario")
def calendario():
    """Vista pública del calendario de eventos del AMPA."""
    return render_template("public/calendario.html")


@public_bp.route("/eventos/<slug>")
@login_required
def evento_detalle(slug):
    if not _can_view_events():
        abort(403)
    return render_template("public/evento_detalle.html", slug=slug)


@public_bp.route("/documentos")
def documentos():
    return render_template("public/documentos.html")


@public_bp.route("/contacto", methods=["GET", "POST"])
def contacto():
    if request.method == "POST":
        from app.services.mail_service import send_contact_email
        
        # Leer datos del formulario
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip()
        asunto = request.form.get("asunto", "").strip()
        mensaje = request.form.get("mensaje", "").strip()
        
        # Validaciones básicas
        errores = []
        
        if not nombre:
            errores.append("El nombre es obligatorio")
        elif len(nombre) > 100:
            errores.append("El nombre es demasiado largo (máximo 100 caracteres)")
        
        if not email:
            errores.append("El email es obligatorio")
        elif len(email) > 150:
            errores.append("El email es demasiado largo")
        elif not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
            errores.append("El formato del email no es válido")
        
        if not asunto:
            errores.append("Debes seleccionar un asunto")
        
        if not mensaje:
            errores.append("El mensaje es obligatorio")
        elif len(mensaje) < 10:
            errores.append("El mensaje es demasiado corto (mínimo 10 caracteres)")
        elif len(mensaje) > 5000:
            errores.append("El mensaje es demasiado largo (máximo 5000 caracteres)")
        
        # Si hay errores, mostrarlos
        if errores:
            for error in errores:
                flash(error, "error")
            return render_template(
                "public/contacto.html",
                form_data={"nombre": nombre, "email": email, "asunto": asunto, "mensaje": mensaje}
            )
        
        # Intentar enviar el correo
        datos_contacto = {
            "nombre": nombre,
            "email": email,
            "asunto": asunto,
            "mensaje": mensaje
        }
        
        resultado = send_contact_email(datos_contacto, current_app.config)
        
        if resultado.get("ok"):
            # Registrar el envío (sin el texto completo del mensaje por privacidad)
            current_app.logger.info(
                f"Correo de contacto enviado - Nombre: {nombre}, Email: {email}, Asunto: {asunto}"
            )
            flash("Tu mensaje ha sido enviado correctamente. Nos pondremos en contacto contigo pronto.", "success")
            return redirect(url_for("public.contacto"))
        else:
            # Registrar el error
            error_msg = resultado.get("error", "Error desconocido")
            current_app.logger.error(f"Error al enviar correo de contacto: {error_msg}")
            flash("No se ha podido enviar el mensaje. Por favor, inténtalo de nuevo más tarde.", "error")
            return render_template(
                "public/contacto.html",
                form_data={"nombre": nombre, "email": email, "asunto": asunto, "mensaje": mensaje}
            )
    
    return render_template("public/contacto.html")


@public_bp.route("/faq")
def faq():
    return render_template("public/faq.html")
