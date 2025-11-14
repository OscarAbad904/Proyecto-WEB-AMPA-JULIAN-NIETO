from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import (
    current_user,
    login_required,
    login_user,
    logout_user,
)

from ..extensions import db, login_manager
from ..forms import (
    CommentForm,
    LoginForm,
    RecoverForm,
    RegisterForm,
    SuggestionForm,
    VoteForm,
)
from ..models import Comment, Role, Suggestion, User, Vote
from ..utils.tokens import generate_confirmation_token

members_bp = Blueprint("members", __name__, template_folder="../../templates/members")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@members_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("members.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash("Bienvenido de nuevo", "success")
            return redirect(url_for("members.dashboard"))
        flash("Credenciales inválidas", "danger")
    return render_template("members/login.html", form=form)


@members_bp.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data.lower()).first():
            flash("Ya existe una cuenta con ese correo", "warning")
            return render_template("members/register.html", form=form)
        role = Role.query.filter_by(name="socio").first()
        if not role:
            role = Role(name="socio")
            db.session.add(role)
            db.session.commit()
        user = User(
            username=form.username.data,
            email=form.email.data.lower(),
            role=role,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        token = generate_confirmation_token(user.email)
        flash("Se ha enviado un correo de verificación", "info")
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
    return render_template("members/dashboard.html")


@members_bp.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    form = RecoverForm()
    if form.validate_on_submit():
        flash("Si existe la cuenta, se ha enviado un enlace de recuperación", "info")
    return render_template("members/recuperar.html", form=form)


@members_bp.route("/sugerencias")
@login_required
def sugerencias():
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
def detalle_sugerencia(suggestion_id):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    comment_form = CommentForm()
    vote_form = VoteForm()
    return render_template(
        "members/sugerencia_detalle.html",
        suggestion=suggestion,
        comment_form=comment_form,
        vote_form=vote_form,
    )


@members_bp.route("/sugerencias/<int:suggestion_id>/comentar", methods=["POST"])
@login_required
def comentar_sugerencia(suggestion_id):
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
def votar_sugerencia(suggestion_id):
    suggestion = Suggestion.query.get_or_404(suggestion_id)
    form = VoteForm()
    if form.validate_on_submit():
        value = int(form.value.data)
        vote = Vote.query.filter_by(user_id=current_user.id, suggestion_id=suggestion.id).first()
        if vote:
            suggestion.votes_count -= vote.value
            vote.value = value
        else:
            vote = Vote(suggestion_id=suggestion.id, user_id=current_user.id, value=value)
            db.session.add(vote)
        suggestion.votes_count += value
        db.session.commit()
        flash("Voto registrado", "success")
    return redirect(url_for("members.detalle_sugerencia", suggestion_id=suggestion_id))
