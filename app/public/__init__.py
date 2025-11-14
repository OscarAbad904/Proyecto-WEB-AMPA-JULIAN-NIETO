from flask import Blueprint, render_template, request, current_app

public_bp = Blueprint("public", __name__, template_folder="../../templates/public")


@public_bp.route("/")
@public_bp.route("/AMPA")
def home():
    return render_template("index.html")


@public_bp.route("/noticias")
def noticias():
    query = request.args.get("q", "")
    return render_template("public/noticias.html", query=query)


@public_bp.route("/noticias/<slug>")
def noticia_detalle(slug):
    return render_template("public/noticia_detalle.html", slug=slug)


@public_bp.route("/eventos")
def eventos():
    return render_template("public/eventos.html")


@public_bp.route("/eventos/<slug>")
def evento_detalle(slug):
    return render_template("public/evento_detalle.html", slug=slug)


@public_bp.route("/documentos")
def documentos():
    return render_template("public/documentos.html")


@public_bp.route("/contacto", methods=["GET", "POST"])
def contacto():
    if request.method == "POST":
        current_app.logger.info("Contacto enviado desde la web pública")
    return render_template("public/contacto.html")


@public_bp.route("/faq")
def faq():
    return render_template("public/faq.html")
