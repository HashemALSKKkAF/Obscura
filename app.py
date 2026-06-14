"""
app.py
OBSCURA web application factory.

Thin composition root: it builds the Flask app and registers the resource
blueprints. Business logic lives in services (pipeline.py, env_manager.py) and
the persistence/provider modules; HTTP handlers live in the web_routes /
api_* blueprints.
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from __version__ import __version__
from api_config import config_bp
from api_investigations import investigations_bp
from api_seeds import seeds_bp
from api_tor import tor_bp
from web_routes import web_bp

load_dotenv()

log = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Log to the console and — when the directory is writable — to a rotating
    file. The `obscura logs` CLI command and any log shipper tail that file, so
    a native run and a container run expose logs the same way. A read-only or
    missing log dir is non-fatal: we keep console logging and move on.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_dir = os.environ.get("OBSCURA_LOG_DIR", str(Path(__file__).parent / "logs"))
    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            Path(log_dir) / "obscura.log", maxBytes=5_000_000, backupCount=5
        )
        handlers.append(file_handler)
    except OSError as exc:  # read-only fs, permissions, etc. — keep console only
        logging.getLogger(__name__).warning(
            "File logging disabled (%s): %s", log_dir, exc
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


_configure_logging()


def create_app() -> Flask:
    """Build and configure the Flask application."""
    # static_folder=None: the web blueprint serves index.html + assets itself,
    # so we don't want Flask's default /static route shadowing the SPA routes.
    app = Flask(__name__, static_folder=None)
    for blueprint in (web_bp, config_bp, investigations_bp, seeds_bp, tor_bp):
        app.register_blueprint(blueprint)
    return app


app = create_app()


if __name__ == "__main__":
    # Bind to localhost by default — OBSCURA has no auth and drives Tor crawling
    # + paid LLM calls, so it should not be exposed on all interfaces unless the
    # operator explicitly opts in via OBSCURA_HOST.
    host = os.environ.get("OBSCURA_HOST", "127.0.0.1")
    port = int(os.environ.get("OBSCURA_PORT", "8501"))
    log.info("OBSCURA %s starting — http://%s:%s", __version__, host, port)
    # threaded=True is required: investigations stream over a long-lived SSE
    # connection while the UI keeps polling (seeds/health). Without it the
    # single-threaded dev server serializes requests, so a second investigation
    # (or a poll) blocks behind the first — the "stuck at initializing" freeze.
    app.run(host=host, port=port, threaded=True)
