from flask import Blueprint, render_template
from flask_login import login_required

admin_bp = Blueprint("admin", __name__, template_folder="../../templates/admin")


@admin_bp.route("/")
@login_required
def dashboard():
    return render_template("admin/dashboard.html")


@admin_bp.route("/posts")
@login_required
def posts():
    return render_template("admin/posts.html")


@admin_bp.route("/eventos")
@login_required
def eventos():
    return render_template("admin/eventos.html")


@admin_bp.route("/sugerencias")
@login_required
def sugerencias():
    return render_template("admin/sugerencias.html")


@admin_bp.route("/usuarios")
@login_required
def usuarios():
    return render_template("admin/usuarios.html")
