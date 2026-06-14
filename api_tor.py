"""
api_tor.py
Tor control endpoint: request a fresh circuit ("new identity").

Wires up tor_utils (previously unreferenced) so OSINT users can rotate their
exit node between investigations and confirm the change via the new exit IP.
"""
from flask import Blueprint, jsonify

import tor_session
import tor_utils

tor_bp = Blueprint("tor", __name__)


@tor_bp.route("/api/tor/newnym", methods=["POST"])
def api_tor_newnym():
    """Signal NEWNYM on the Tor control port and report the resulting exit IP.

    Returns 200 with the result dict in all cases; ``status`` ("ok"/"error")
    and ``message`` carry the outcome so the UI can show actionable guidance
    (e.g. "enable ControlPort in your torrc").
    """
    result = tor_utils.refresh_tor_circuit()
    if result.get("status") == "ok":
        exit_ip = tor_utils.get_tor_exit_ip(tor_session.get_tor_session())
        if exit_ip:
            result["exit_ip"] = exit_ip
    return jsonify(result)
