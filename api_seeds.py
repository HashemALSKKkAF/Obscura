"""
api_seeds.py
Seed-URL endpoints: list/add (with background auto-crawl), manual crawl, delete.
"""
import logging
import threading

from flask import Blueprint, jsonify, request

import seeds as seed_db
from crawler import crawl_sources

seeds_bp = Blueprint("seeds", __name__)


def _auto_crawl_seed(seed_id, seed_url, seed_name):
    """Background crawl for a freshly-added seed so the Seed Manager fills in
    crawled content without a manual deep-crawl."""
    try:
        results = crawl_sources([{"link": seed_url, "title": seed_name}], max_workers=1)
        text = results.get(seed_url)
        if text:
            seed_db.mark_crawled(seed_id, status_code=200, content=text)
        else:
            # mark crawled with empty content so it won't be repeatedly retried
            seed_db.mark_crawled(seed_id, status_code=None, content="")
    except Exception:
        logging.exception("Auto-crawl failed for seed %s", seed_url)


@seeds_bp.route("/api/seeds", methods=["GET", "POST"])
def api_seeds():
    if request.method == "GET":
        return jsonify({"seeds": seed_db.get_all_seeds()})

    data = request.get_json(force=True) or {}
    url_value = data.get("url")
    if isinstance(url_value, dict):
        url_value = url_value.get("text") or str(url_value)
    if not isinstance(url_value, str):
        return jsonify({"error": "Seed URL must be a valid string."}), 400
    url = url_value.strip()
    name_value = data.get("name")
    if isinstance(name_value, dict):
        name_value = name_value.get("text") or str(name_value)
    name = (name_value or "").strip()
    if not url:
        return jsonify({"error": "URL is required."}), 400

    try:
        seed = seed_db.add_seed(url, name)
        try:
            sid = seed.get("id") if isinstance(seed, dict) else None
            if sid:
                threading.Thread(
                    target=_auto_crawl_seed,
                    args=(sid, seed.get("url"), seed.get("name")),
                    daemon=True,
                ).start()
        except Exception:
            logging.exception("Failed to start auto-crawl thread")
        return jsonify({"seed": seed})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@seeds_bp.route("/api/seeds/<int:seed_id>/crawl", methods=["POST"])
def api_crawl_seed(seed_id):
    """Manually trigger a synchronous crawl for a specific seed id."""
    try:
        seeds = seed_db.get_all_seeds() or []
        seed = next((s for s in seeds if int(s.get("id")) == int(seed_id)), None)
        if not seed:
            return jsonify({"error": "Seed not found."}), 404

        results = crawl_sources([{"link": seed.get("url"), "title": seed.get("name", "")}], max_workers=1)
        text = results.get(seed.get("url"))
        if text:
            seed_db.mark_crawled(seed_id, status_code=200, content=text)
        else:
            seed_db.mark_crawled(seed_id, status_code=None, content="")
        return jsonify({"result": {"url": seed.get("url"), "text": text}})
    except Exception as exc:
        logging.exception("Manual seed crawl failed")
        return jsonify({"error": str(exc)}), 500


@seeds_bp.route("/api/seeds/<int:seed_id>", methods=["DELETE", "POST"])
def api_delete_seed(seed_id):
    try:
        seed_db.delete_seed(seed_id)
        return jsonify({"deleted": True})
    except Exception as exc:
        logging.exception("Failed to delete seed %s", seed_id)
        return jsonify({"error": str(exc)}), 500
