"""web_routes.py — serves the single-page frontend (index.html + static assets)."""
from pathlib import Path

from flask import Blueprint, send_from_directory

APP_DIR = Path(__file__).resolve().parent

web_bp = Blueprint("web", __name__)


@web_bp.route("/", methods=["GET"])
def serve_index():
    return send_from_directory(APP_DIR, "index.html")


@web_bp.route("/<path:path>", methods=["GET"])
def serve_static(path):
    # Resolve against the app directory (not the CWD) and fall back to the SPA
    # entry point for client-side routes. send_from_directory guards traversal.
    if (APP_DIR / path).is_file():
        return send_from_directory(APP_DIR, path)
    return send_from_directory(APP_DIR, "index.html")
