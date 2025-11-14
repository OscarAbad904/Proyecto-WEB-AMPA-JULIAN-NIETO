from flask import Blueprint, jsonify

api_bp = Blueprint("api", __name__)


@api_bp.route("/status")
def status():
    return jsonify({"status": "ok", "service": "AMPA Julián Nieto", "version": "0.1"})


@api_bp.route("/publicaciones")
def publicaciones():
    return jsonify({"items": [], "pagination": {"page": 1, "per_page": 10}})
