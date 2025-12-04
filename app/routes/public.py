from flask import Blueprint, render_template, request, current_app, flash, redirect, url_for
import re
from app.models import Post
from app.utils import _normalize_drive_url

public_bp = Blueprint("public", __name__, template_folder="../../templates/public")

@public_bp.route("/")
@public_bp.route("/AMPA")
def home():
    return render_template("index.html")


@public_bp.route("/quienes-somos")
def quienes_somos():
    return render_template("public/quienes_somos.html")


@public_bp.route("/noticias")
def noticias():
    query = request.args.get("q", "")
    posts = (
        Post.query.filter_by(status="published")
        .order_by(Post.published_at.desc().nullslast(), Post.created_at.desc())
        .all()
    )
    for post in posts:
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
    # Siempre obtener las 3 noticias más recientes (por published_at descendente)
    latest_three: list[Post] = posts[:3]
    
    # Reordenar las 3 más recientes según featured_position si existen
    posts_with_position = [p for p in latest_three if p.featured_position is not None]
    posts_without_position = [p for p in latest_three if p.featured_position is None]
    
    # Ordenar solo los que tienen featured_position
    posts_with_position.sort(key=lambda p: p.featured_position or 0)
    
    # Combinar: primero los que tienen posición (ordenados), luego los demás
    latest_three = posts_with_position + posts_without_position
    return render_template("public/noticias.html", query=query, posts=posts, latest_three=latest_three)


@public_bp.route("/noticias/<slug>")
def noticia_detalle(slug):
    return render_template("public/noticia_detalle.html", slug=slug)


@public_bp.route("/eventos")
def eventos():
    return render_template("public/eventos.html")


@public_bp.route("/calendario")
def calendario():
    """Vista pública del calendario de eventos del AMPA."""
    return render_template("public/calendario.html")


@public_bp.route("/eventos/<slug>")
def evento_detalle(slug):
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
