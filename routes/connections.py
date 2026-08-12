"""
routes/connections.py
======================
Social publishing connections: view non-sensitive parameters + live status of the
YouTube, Instagram, and Facebook integrations, test each connection, and set up /
reset the Facebook Page credentials.

Secrets are NEVER returned by these endpoints. App IDs/secrets live in .env and
are reported only as presence booleans; runtime tokens live in their own creds
files and are reported only as status/expiry.
"""

import json
import os
import time
from pathlib import Path

from flask import Blueprint, request, jsonify

bp = Blueprint("connections", __name__, url_prefix="")


def _days_left(expiry_ts) -> int:
    try:
        return max(0, int((float(expiry_ts) - time.time()) / 86400))
    except (TypeError, ValueError):
        return 0


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


# =============================================================================
# AGGREGATE STATUS  (no secrets)
# =============================================================================

@bp.route("/connections", methods=["GET"])
def connections_status():
    # ── YouTube ──────────────────────────────────────────────────────────────
    token_exists  = Path("token.json").exists()
    yt_client_env = bool(os.getenv("GOOGLE_CLIENT_ID", "").strip()
                         and os.getenv("GOOGLE_CLIENT_SECRET", "").strip())
    yt_client_file = Path("client_secret.json").exists()
    youtube = {
        "configured":        token_exists,
        "token_exists":      token_exists,
        "client_env_set":    yt_client_env,
        "client_file_set":   yt_client_file,
        "client_configured": yt_client_env or yt_client_file,
    }

    # ── Instagram ────────────────────────────────────────────────────────────
    ig_creds = _read_json(Path("instagram_creds.json"))
    instagram = {
        "configured":     bool(ig_creds),
        "app_id_set":     bool(os.getenv("FB_APP_ID", "").strip()),
        "app_secret_set": bool(os.getenv("FB_APP_SECRET", "").strip()),
        "ig_user_id":     ig_creds.get("ig_user_id", ""),
        "days_left":      _days_left(ig_creds.get("expiry_ts")) if ig_creds else 0,
    }

    # ── Facebook ─────────────────────────────────────────────────────────────
    fb_creds = _read_json(Path("facebook_creds.json"))
    fb_expiry = fb_creds.get("expiry_ts", 0)
    facebook = {
        "configured":     bool(fb_creds),
        "app_id_set":     bool(os.getenv("FB_APP_ID", "").strip()),
        "app_secret_set": bool(os.getenv("FB_APP_SECRET", "").strip()),
        "page_id":        fb_creds.get("page_id", ""),
        "page_name":      fb_creds.get("page_name", ""),
        # expiry_ts == 0 means a non-expiring Page token.
        "non_expiring":   bool(fb_creds) and not fb_expiry,
        "days_left":      _days_left(fb_expiry) if fb_expiry else 0,
    }

    return jsonify({"youtube": youtube, "instagram": instagram, "facebook": facebook})


# =============================================================================
# TESTS
# -----------------------------------------------------------------------------
# Each test makes ONE lightweight authenticated call to the platform (read the
# channel / the logged-in user / the Page) to prove the stored credentials still
# work. They run synchronously (unlike uploads, which use run_job in a background
# thread) because they finish in a second or two, and they never raise — any error
# is caught and returned as {ok: false, detail: "..."} so the UI can show the exact
# platform message instead of a generic 500.
# =============================================================================

@bp.route("/connections/youtube/test", methods=["POST"])
def test_youtube():
    try:
        from upload_video import get_channel_info
        info = get_channel_info()
        if info.get("scope_limited"):
            detail = "Authenticated — token is valid (upload scope; channel name needs the youtube.readonly scope)"
        else:
            detail = "Connected as channel: " + (info.get("title") or "(unnamed)")
        return jsonify({"ok": True, "detail": detail, "channel": info})
    except Exception as e:
        return jsonify({"ok": False, "detail": str(e)})


@bp.route("/connections/instagram/test", methods=["POST"])
def test_instagram():
    try:
        import requests as req
        from upload_instagram import get_valid_token, GRAPH_BASE
        token, ig_user_id = get_valid_token()
        me = req.get(GRAPH_BASE + "/me",
                     params={"access_token": token, "fields": "id,name"}, timeout=15).json()
        if "error" in me:
            return jsonify({"ok": False, "detail": str(me["error"])})
        name = me.get("name", "")
        return jsonify({"ok": True,
                        "detail": f"Connected as {name} — IG user {ig_user_id}",
                        "account": {"name": name, "ig_user_id": ig_user_id}})
    except Exception as e:
        return jsonify({"ok": False, "detail": str(e)})


@bp.route("/connections/facebook/test", methods=["POST"])
def test_facebook():
    try:
        from upload_facebook import get_valid_token, get_page_info
        token, page_id = get_valid_token()
        info = get_page_info(token, page_id)
        name = info.get("name", "")
        return jsonify({"ok": True,
                        "detail": f"Connected to Page: {name} ({page_id})",
                        "page": info})
    except Exception as e:
        return jsonify({"ok": False, "detail": str(e)})


# =============================================================================
# FACEBOOK SETUP / STATUS / RESET
# =============================================================================

@bp.route("/auth/facebook/setup", methods=["POST"])
def facebook_setup():
    try:
        data          = request.get_json() or {}
        page_id       = (data.get("page_id") or "").strip()
        token         = (data.get("token") or "").strip()
        is_page_token = bool(data.get("is_page_token", False))
        if not page_id or not token:
            return jsonify({"error": "page_id and token are required"}), 400
        from upload_facebook import setup
        result = setup(page_id, token, is_page_token=is_page_token)
        return jsonify({"message": "Facebook Page connected: " + (result.get("page_name") or page_id),
                        **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/auth/facebook/status", methods=["GET"])
def facebook_status():
    creds = _read_json(Path("facebook_creds.json"))
    if not creds:
        return jsonify({"configured": False})
    return jsonify({"configured": True,
                    "page_id": creds.get("page_id", ""),
                    "page_name": creds.get("page_name", "")})


@bp.route("/auth/facebook/reset", methods=["POST"])
def facebook_reset():
    try:
        from upload_facebook import reset_auth
        reset_auth()
        return jsonify({"message": "Facebook credentials cleared."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
