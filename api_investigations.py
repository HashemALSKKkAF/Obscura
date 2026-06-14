"""
api_investigations.py
Investigation endpoints: CRUD, metadata, resummarize, deep-crawl, the streaming
investigate pipeline, and PDF export.
"""
import json
import logging
from datetime import datetime

from flask import Blueprint, Response, jsonify, make_response, request

import investigations as inv_db
import seeds as seed_db
from crawler import crawl_sources, probe_tier
from export import generate_pdf
from llm import generate_summary, get_llm
from pipeline import InvestigationPipeline
from scrape import scrape_multiple

investigations_bp = Blueprint("investigations", __name__)


def _preserve_investigation(inv: dict) -> dict:
    """Project a stored investigation onto the stable API response shape."""
    return {
        "id": inv.get("id"),
        "timestamp": inv.get("timestamp"),
        "query": inv.get("query"),
        "refined_query": inv.get("refined_query"),
        "model": inv.get("model"),
        "preset": inv.get("preset"),
        "summary": inv.get("summary"),
        "status": inv.get("status"),
        "tags": inv.get("tags"),
        "sources": inv.get("sources") or [],
    }


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _as_int(value, default: int) -> int:
    """Coerce a request value to int, falling back to default on bad input
    (so a malformed tuning param yields a sane default, not a 500)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ── CRUD ──────────────────────────────────────────────────────────────────────

@investigations_bp.route("/api/investigations", methods=["GET"])
def api_investigations():
    invs = inv_db.load_all()
    return jsonify({
        "investigations": [_preserve_investigation(inv) for inv in invs],
        "tags": inv_db.get_all_tags(),
    })


@investigations_bp.route("/api/investigations/<int:inv_id>", methods=["GET", "DELETE"])
def api_investigation_item(inv_id):
    if request.method == "DELETE":
        inv_db.delete_investigation(inv_id)
        return jsonify({"deleted": True})
    inv = inv_db.load_one(inv_id)
    if not inv:
        return jsonify({"error": "Investigation not found."}), 404
    return jsonify(_preserve_investigation(inv))


@investigations_bp.route("/api/investigations/<int:inv_id>/metadata", methods=["PUT"])
def api_update_investigation_metadata(inv_id):
    inv = inv_db.load_one(inv_id)
    if not inv:
        return jsonify({"error": "Investigation not found."}), 404
    data = request.get_json(force=True) or {}
    status = data.get("status")
    tags = data.get("tags")
    try:
        if status is not None:
            inv_db.update_status(inv_id, status)
        if tags is not None:
            inv_db.update_tags(inv_id, tags)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    inv = inv_db.load_one(inv_id)
    return jsonify(_preserve_investigation(inv))


# ── Resummarize ─────────────────────────────────────────────────────────────

@investigations_bp.route("/api/investigations/<int:inv_id>/resummarize", methods=["POST"])
def api_resummarize_investigation(inv_id):
    inv = inv_db.load_one(inv_id)
    if not inv:
        return jsonify({"error": "Investigation not found."}), 404
    data = request.get_json(force=True) or {}
    # Allow callers to force a full re-scrape/resummarize by setting this flag.
    force_rescrape = bool(data.get("force_rescrape"))
    model = data.get("model") or inv.get("model")
    preset = data.get("preset") or inv.get("preset")
    custom_instructions = data.get("custom_instructions", "")
    system_prompt_override = data.get("system_prompt_override")
    try:
        llm = get_llm(model)
        # Build a 'scraped' mapping from saved seed content where possible.
        # By default missing sources are NOT re-scraped (avoids crawling);
        # force_rescrape scrapes only the missing ones.
        scraped = {}
        sources = inv.get("sources", []) or []
        missing_sources = []
        for src in sources:
            link = src.get("link")
            try:
                s = seed_db.get_seed_by_url(link)
            except Exception:
                s = None
            if s and s.get("content"):
                scraped[link] = s.get("content")
            else:
                missing_sources.append(src)

        if force_rescrape and missing_sources:
            scraped_missing = scrape_multiple(missing_sources, max_workers=4, max_return_chars=2000)
            for k, v in (scraped_missing or {}).items():
                scraped[k] = v

        # No fresh page content but a saved summary exists → re-condense that
        # text (no network I/O).
        if not scraped and inv.get("summary"):
            scraped = {"_existing_summary": inv.get("summary")}
        summary = generate_summary(
            llm,
            inv.get("query", ""),
            scraped,
            preset=preset,
            custom_instructions=custom_instructions,
            system_prompt_override=system_prompt_override,
        )
        inv_db.update_summary(
            inv_id, summary, refined_query=inv.get("refined_query", ""), model=model, preset_label=preset
        )
        try:
            inv_db.update_status(inv_id, "complete")
        except Exception:
            # ignore if status value is unexpected for older DBs
            pass
        updated = inv_db.load_one(inv_id)
        return jsonify(_preserve_investigation(updated))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Deep crawl ──────────────────────────────────────────────────────────────

@investigations_bp.route("/api/investigations/<int:inv_id>/deep-crawl", methods=["POST"])
def api_deep_crawl_investigation(inv_id):
    inv = inv_db.load_one(inv_id)
    if not inv:
        return jsonify({"error": "Investigation not found."}), 404
    try:
        tier = probe_tier()
        crawled = crawl_sources(inv.get("sources", []), max_workers=4, tier=tier)
        # Persist crawled source content as seeds when possible.
        for source in inv.get("sources", []):
            if source.get("link") in crawled:
                try:
                    db_seed = seed_db.add_seed(source.get("link"), source.get("title", ""))
                    if db_seed:
                        seed_db.mark_crawled(db_seed["id"], status_code=200, content=crawled[source.get("link")])
                except Exception:
                    pass
        return jsonify(_preserve_investigation(inv))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Investigate (streaming) ──────────────────────────────────────────────────

@investigations_bp.route("/api/investigate", methods=["POST"])
def api_investigate():
    data = request.get_json(force=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Query is required."}), 400

    model = data.get("model")
    if not model:
        return jsonify({"error": "LLM model selection is required."}), 400

    preset = data.get("preset") or "threat_intel"
    threads = _as_int(data.get("threads"), 4)
    max_results = _as_int(data.get("max_results"), 50)
    max_scrape = _as_int(data.get("max_scrape"), 10)
    max_content_chars = _as_int(data.get("max_content_chars"), 2000)

    try:
        llm = get_llm(model)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    pipeline = InvestigationPipeline(llm)

    def generate():
        try:
            for event in pipeline.run(
                query=query, model=model, preset=preset, threads=threads,
                max_results=max_results, max_scrape=max_scrape,
                max_content_chars=max_content_chars,
            ):
                if event.get("done"):
                    inv = inv_db.load_one(event["inv_id"])
                    response = _preserve_investigation(inv)
                    response.update({
                        "results": event["results"],
                        "filtered": event["filtered"],
                        "scraped": event["scraped"],
                        "done": True,
                    })
                    yield _sse(response)
                else:
                    yield _sse(event)
        except Exception as exc:
            logging.exception("investigation failed")
            yield _sse({"error": str(exc)})

    # Headers that keep the event stream un-buffered so the UI shows each stage
    # as it happens (Cache-Control for browsers, X-Accel-Buffering for proxies).
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Export ────────────────────────────────────────────────────────────────────

@investigations_bp.route("/api/export/pdf", methods=["POST"])
def api_export_pdf():
    data = request.get_json(force=True) or {}
    pdf_data = data.get("summary")
    metadata = data.get("metadata") or {}
    if not pdf_data:
        return jsonify({"error": "Summary content is required."}), 400
    inv = {
        "query": metadata.get("query", ""),
        "refined_query": metadata.get("refined_query", ""),
        "model": metadata.get("model", ""),
        "preset": metadata.get("preset", ""),
        "status": metadata.get("status", "active"),
        "tags": metadata.get("tags", ""),
        "timestamp": metadata.get("timestamp") or datetime.now().isoformat(),
        "sources": metadata.get("sources", []),
        "summary": pdf_data,
    }
    try:
        pdf_bytes = generate_pdf(inv)
        response = make_response(pdf_bytes)
        response.headers["Content-Type"] = "application/pdf"
        response.headers["Content-Disposition"] = (
            f"attachment; filename=obscura_investigation_{datetime.now().strftime('%Y-%m-%d')}.pdf"
        )
        return response
    except Exception as exc:
        logging.exception("PDF export failed")
        return jsonify({"error": str(exc)}), 500
