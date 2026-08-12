"""
upload_facebook.py
==================
Upload the final project video to a Facebook Page — as a feed video or a Reel.

This is a STANDALONE integration, independent of the Instagram publisher
(upload_instagram.py). It talks to a Facebook Page directly using that Page's
own access token, so it does not need an Instagram Business account or the
linked-account discovery that the Instagram flow relies on.

SECRETS (hybrid model)
----------------------
The Facebook App ID / App Secret are read from the environment (.env):

    FB_APP_ID=...
    FB_APP_SECRET=...

Only the runtime values (the resolved Page ID + long-lived Page access token)
are written to facebook_creds.json.

SETUP (one-time)
----------------
1. https://developers.facebook.com → your App (same app as Instagram is fine)
2. Graph API Explorer → generate a User Access Token with:
       pages_show_list, pages_read_engagement, pages_manage_posts
3. Save it via the Connections page (App ID/Secret come from .env), giving the
   target Page ID. The backend exchanges the user token for a long-lived one and
   resolves the Page's own (non-expiring) access token.

   Alternatively you can paste a Page access token directly (is_page_token=True).

How the connection works (and why it's separate from Instagram)
---------------------------------------------------------------
Both this file and upload_instagram.py speak to the same Facebook Graph API, but
they authenticate against different objects — and that distinction is the whole
reason this module exists separately:

  - Instagram publishing needs a Facebook Page that has an Instagram Business
    account linked to it, then targets that IG account. If the linkage is missing
    or misconfigured, the Instagram flow can't find an account to post to.

  - Facebook Page publishing targets the Page directly. It only needs a *Page
    access token* — a token scoped to one Page — and the Page id. No Instagram
    account, no linked-account discovery, nothing shared with the IG flow.

Two kinds of token appear here (`setup`):
  1. A *User access token* (default): identifies you, the person. We exchange it for
     a long-lived user token, then call /me/accounts and read the Page's own
     `access_token` field. A Page token derived from a *long-lived* user token does
     not expire, which is why we store expiry_ts = 0 (non-expiring).
  2. A *Page access token* (is_page_token=True): already scoped to the Page, so we
     store it as-is after a quick validity check.

Publishing then differs by product: a normal feed video is one multipart POST to
/{page-id}/videos; a Reel uses a three-phase start → upload → finish handshake.

USAGE
-----
    python upload_facebook.py --project my_project
    python upload_facebook.py --project my_project --reel
    python upload_facebook.py --file path/to/video.mp4 --description "..."

NOTES
-----
- Reels must be vertical 9:16.
- pip install requests
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

GRAPH_BASE     = "https://graph.facebook.com/v25.0"
GRAPH_VIDEO    = "https://graph-video.facebook.com/v25.0"
CREDS_FILE     = Path("facebook_creds.json")
REEL_POLL_INTERVAL = 10
REEL_POLL_TIMEOUT  = 300


# =============================================================================
# ENV / CREDENTIALS
# =============================================================================

def _app_credentials() -> tuple:
    """Return (app_id, app_secret) from the environment (.env). Either may be "" ."""
    return os.getenv("FB_APP_ID", "").strip(), os.getenv("FB_APP_SECRET", "").strip()


def _load_creds() -> dict:
    if not CREDS_FILE.exists():
        raise FileNotFoundError(
            "facebook_creds.json not found.\n"
            "Configure the Facebook connection on the Connections page."
        )
    with open(CREDS_FILE) as f:
        return json.load(f)


def _save_creds(creds: dict) -> None:
    with open(CREDS_FILE, "w") as f:
        json.dump(creds, f, indent=2)
    logger.debug("Credentials saved to %s", CREDS_FILE)


def _exchange_for_long_lived(app_id: str, app_secret: str, short_token: str) -> dict:
    """
    Exchange a short-lived user token for a long-lived one (~60 days).
    On a 400 (e.g. token already long-lived), inspect via /debug_token and use as-is.
    """
    r = requests.get(
        GRAPH_BASE + "/oauth/access_token",
        params={
            "grant_type":        "fb_exchange_token",
            "client_id":         app_id,
            "client_secret":     app_secret,
            "fb_exchange_token": short_token,
        },
        timeout=30,
    )
    if r.status_code == 400:
        try:
            fb_err = r.json()
        except Exception:
            fb_err = r.text
        logger.warning("Token exchange returned 400: %s -- trying debug_token fallback", fb_err)
        debug = requests.get(
            GRAPH_BASE + "/debug_token",
            params={"input_token": short_token,
                    "access_token": str(app_id) + "|" + str(app_secret)},
            timeout=30,
        )
        if debug.ok:
            ddata = debug.json().get("data", {})
            expires_at = ddata.get("expires_at", 0)
            expires_in = 60 * 86400 if expires_at == 0 else max(0, int(expires_at - time.time()))
            return {"access_token": short_token, "expires_in": expires_in}
        raise RuntimeError(
            "Token exchange failed (400). Facebook said: " + str(fb_err) + "\n"
            "Make sure you are using a User Access Token from the Graph API Explorer."
        )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError("Token exchange failed: " + str(data["error"]))
    return data


def _resolve_page_token(user_token: str, page_id: str) -> tuple:
    """Find the Page access token for *page_id* among the user's managed Pages.

    Returns (page_name, page_access_token).
    """
    r = requests.get(
        GRAPH_BASE + "/me/accounts",
        params={"access_token": user_token, "fields": "id,name,access_token", "limit": 200},
        timeout=20,
    )
    r.raise_for_status()
    pages = r.json().get("data", [])
    # Each managed Page carries its own `access_token` — a Page-scoped token distinct
    # from the user token we queried with. That Page token is what we store and post
    # with; when derived from a long-lived user token it does not expire.
    for page in pages:
        if str(page.get("id")) == str(page_id):
            logger.info("Resolved Page token for '%s' (%s)", page.get("name"), page_id)
            return page.get("name", ""), page["access_token"]
    available = ", ".join(f"{p.get('name')} ({p.get('id')})" for p in pages) or "(none)"
    raise RuntimeError(
        "Page ID " + str(page_id) + " not found among your managed Pages.\n"
        "Pages available with this token: " + available + "\n"
        "Make sure the token has pages_show_list and you are an admin of the Page."
    )


def setup(page_id: str, token: str, is_page_token: bool = False) -> dict:
    """One-time setup: resolve and store the Page's long-lived access token.

    - is_page_token=False (default): *token* is a User Access Token. It is
      exchanged for a long-lived user token, then the Page access token for
      *page_id* is looked up (Page tokens derived this way do not expire).
    - is_page_token=True: *token* is already a Page access token; stored as-is.

    Returns the stored creds (without the token) for convenience.
    """
    if is_page_token:
        page_token = token
        # Confirm it works and grab the page name.
        info = get_page_info(page_token, page_id)
        page_name = info.get("name", "")
        expiry_ts = 0  # unknown / treat as non-expiring
    else:
        app_id, app_secret = _app_credentials()
        if not app_id or not app_secret:
            raise RuntimeError(
                "FB_APP_ID / FB_APP_SECRET are not set in the environment (.env). "
                "Add them, or paste a Page access token directly."
            )
        ll = _exchange_for_long_lived(app_id, app_secret, token)
        user_token = ll["access_token"]
        page_name, page_token = _resolve_page_token(user_token, page_id)
        # Page tokens off a long-lived user token are effectively non-expiring.
        expiry_ts = 0

    creds = {
        "page_id":           str(page_id),
        "page_name":         page_name,
        "page_access_token": page_token,
        "expiry_ts":         expiry_ts,
    }
    _save_creds(creds)
    logger.info("Facebook setup complete for Page '%s' (%s).", page_name, page_id)
    return {"page_id": str(page_id), "page_name": page_name}


def get_valid_token() -> tuple:
    """Return (page_access_token, page_id) from stored creds."""
    creds = _load_creds()
    return creds["page_access_token"], creds["page_id"]


def reset_auth() -> None:
    if CREDS_FILE.exists():
        CREDS_FILE.unlink()
        logger.info("Deleted %s", CREDS_FILE)
    else:
        logger.info("No credentials file found -- nothing to reset.")


def get_page_info(token: str, page_id: str) -> dict:
    """Return {id, name, fan_count?} for the Page — used by the connection test."""
    r = requests.get(
        GRAPH_BASE + "/" + str(page_id),
        params={"access_token": token, "fields": "id,name,fan_count"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(str(data["error"]))
    return data


# =============================================================================
# UPLOAD
# =============================================================================

def _extract_cover_frame(file_path: Path, offset_ms: int) -> Path:
    """Grab a single frame at *offset_ms* into the video as a JPEG (for the Page
    feed-video `thumb`). Unlike Instagram — which takes a thumb_offset number and
    extracts the frame server-side — Facebook's feed endpoint wants the actual
    image bytes, so we pull the frame locally with ffmpeg (already a project dep).

    Returns the temp JPEG path; the caller is responsible for deleting it.
    """
    seconds = max(0, offset_ms) / 1000.0
    out = Path(tempfile.gettempdir()) / f"fb_cover_{os.getpid()}_{int(time.time())}.jpg"
    # -ss before -i = fast (keyframe) seek; -frames:v 1 = one frame; -q:v 3 = good JPEG.
    cmd = ["ffmpeg", "-y", "-ss", f"{seconds:.3f}", "-i", str(file_path),
           "-frames:v", "1", "-q:v", "3", str(out)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError(
            "Could not extract the cover frame with ffmpeg (" + str(e) + "). "
            "Ensure ffmpeg is on PATH, or leave the cover frame blank."
        )
    if not out.exists():
        raise RuntimeError("ffmpeg produced no cover frame for offset " + str(offset_ms) + " ms.")
    return out


def _upload_feed_video(page_id: str, token: str, file_path: Path,
                       title: str, description: str,
                       thumb_path: Path = None,
                       scheduled_publish_time: int = None) -> str:
    """Publish a standard Page feed video via a single multipart request.

    thumb_path (optional): a local image used as the video thumbnail.
    scheduled_publish_time (optional): unix timestamp. When set, the video is
    created UNPUBLISHED (`published=false`) and Facebook auto-publishes it at that
    time — the same pattern YouTube uses with publishAt.
    """
    when = "scheduled for " + time.strftime("%Y-%m-%d %H:%M", time.localtime(scheduled_publish_time)) \
           if scheduled_publish_time else "publishing now"
    logger.info("Uploading feed video %s (%.1f MB) — %s ...",
                file_path.name, file_path.stat().st_size / 1e6, when)

    data = {"access_token": token, "title": title, "description": description}
    if scheduled_publish_time:
        data["published"] = "false"
        data["scheduled_publish_time"] = str(int(scheduled_publish_time))

    files = {"source": (file_path.name, open(file_path, "rb"), "application/octet-stream")}
    thumb_fh = None
    if thumb_path is not None:
        thumb_fh = open(thumb_path, "rb")
        files["thumb"] = (thumb_path.name, thumb_fh, "image/jpeg")
    try:
        r = requests.post(GRAPH_VIDEO + "/" + str(page_id) + "/videos",
                          data=data, files=files, timeout=600)
    finally:
        files["source"][1].close()
        if thumb_fh:
            thumb_fh.close()
    r.raise_for_status()
    payload = r.json()
    if "error" in payload:
        raise RuntimeError("Feed video upload failed: " + str(payload["error"]))
    return payload.get("id", "")


def _upload_reel(page_id: str, token: str, file_path: Path, description: str,
                 scheduled_publish_time: int = None) -> str:
    """Publish a Page Reel via the three-phase Reels API (start → upload → finish).

    scheduled_publish_time (optional): unix timestamp. When set, the finish phase
    uses video_state=SCHEDULED instead of PUBLISHED and Facebook publishes the Reel
    at that time (Reels allow scheduling 10 min – 29 days out).
    """
    # Phase 1 — start: reserve a video id and get the resumable upload URL.
    start = requests.post(
        GRAPH_BASE + "/" + str(page_id) + "/video_reels",
        params={"access_token": token, "upload_phase": "start"},
        timeout=30,
    )
    start.raise_for_status()
    sdata = start.json()
    if "error" in sdata:
        raise RuntimeError("Reel start failed: " + str(sdata["error"]))
    video_id   = sdata["video_id"]
    upload_url = sdata["upload_url"]

    # Phase 2 — upload the bytes.
    file_size = file_path.stat().st_size
    logger.info("Uploading Reel %s (%.1f MB) ...", file_path.name, file_size / 1e6)
    with open(file_path, "rb") as fh:
        r = requests.post(
            upload_url,
            headers={
                "Authorization": "OAuth " + token,
                "offset":        "0",
                "file_size":     str(file_size),
            },
            data=fh.read(),
            timeout=600,
        )
    r.raise_for_status()

    # Phase 3 — finish: publish now, or schedule for later.
    finish_params = {
        "access_token":  token,
        "upload_phase":  "finish",
        "video_id":      video_id,
        "video_state":   "SCHEDULED" if scheduled_publish_time else "PUBLISHED",
        "description":   description,
    }
    if scheduled_publish_time:
        finish_params["scheduled_publish_time"] = str(int(scheduled_publish_time))
    finish = requests.post(
        GRAPH_BASE + "/" + str(page_id) + "/video_reels",
        params=finish_params,
        timeout=30,
    )
    finish.raise_for_status()
    fdata = finish.json()
    if "error" in fdata:
        raise RuntimeError("Reel finish failed: " + str(fdata["error"]))

    # Poll processing status so failures surface here rather than silently.
    # A scheduled Reel never reaches "published" now, so "scheduled" also ends the wait.
    deadline = time.time() + REEL_POLL_TIMEOUT
    while time.time() < deadline:
        s = requests.get(
            GRAPH_BASE + "/" + video_id,
            params={"access_token": token, "fields": "status"},
            timeout=15,
        )
        s.raise_for_status()
        status = (s.json().get("status") or {})
        vs = status.get("video_status") or status.get("processing_phase", {}).get("status")
        logger.info("  Reel status: %s", vs)
        if vs in ("ready", "published", "PUBLISHED", "scheduled", "SCHEDULED"):
            break
        if vs in ("error", "ERROR"):
            raise RuntimeError("Reel processing failed: " + str(status))
        time.sleep(REEL_POLL_INTERVAL)
    return video_id


def upload_facebook(file_path: Path, title: str = "", description: str = "",
                    as_reel: bool = False, thumb_offset_ms: int = None,
                    scheduled_publish_time: int = None) -> str:
    """Upload *file_path* to the configured Page. Returns the video/reel id.

    thumb_offset_ms (optional): cover-frame position for FEED videos (a frame is
        extracted with ffmpeg). Ignored for Reels — the Reels publish call has no
        thumbnail parameter.
    scheduled_publish_time (optional): unix timestamp; schedules the post for later.
    """
    if not file_path.exists():
        raise FileNotFoundError("Video file not found: " + str(file_path))
    token, page_id = get_valid_token()

    if as_reel:
        if thumb_offset_ms is not None:
            logger.warning("Cover frame is not supported for Facebook Reels — ignoring it.")
        vid = _upload_reel(page_id, token, file_path, description,
                           scheduled_publish_time=scheduled_publish_time)
        logger.info("Reel %s! Video ID: %s",
                    "scheduled" if scheduled_publish_time else "published", vid)
    else:
        thumb_path = None
        try:
            if thumb_offset_ms is not None:
                thumb_path = _extract_cover_frame(file_path, thumb_offset_ms)
            vid = _upload_feed_video(page_id, token, file_path, title, description,
                                     thumb_path=thumb_path,
                                     scheduled_publish_time=scheduled_publish_time)
        finally:
            if thumb_path is not None:
                thumb_path.unlink(missing_ok=True)
        logger.info("Feed video %s! Video ID: %s",
                    "scheduled" if scheduled_publish_time else "published", vid)
    logger.info("View at: https://www.facebook.com/%s", vid)
    return vid


# =============================================================================
# MANIFEST / CAPTION (reuse the Instagram helpers — pure, no API coupling)
# =============================================================================

def _final_video_path(project_name: str) -> Path:
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read("config.ini")
        projects_dir = Path(cfg["paths"]["projects_dir"])
    except Exception:
        projects_dir = Path("projects")
    return projects_dir / project_name / ("final_" + project_name + ".mp4")


# =============================================================================
# CLI
# =============================================================================

def main():
    p = argparse.ArgumentParser(description="Upload a project video to a Facebook Page.")
    p.add_argument("--project",     help="Project name (reads manifest for title/caption)")
    p.add_argument("--file",        type=Path, help="Explicit video file path")
    p.add_argument("--title",       help="Override video title (feed videos only)")
    p.add_argument("--description", help="Override description/caption")
    p.add_argument("--reel",        action="store_true", help="Publish as a Reel (vertical 9:16)")
    p.add_argument("--cover-ms",    dest="cover_ms", type=int,
                   help="Cover-frame position in milliseconds (feed videos only)")
    p.add_argument("--publish-at",  dest="publish_at",
                   help="Schedule release: unix timestamp or ISO 8601 (e.g. 2026-09-01T17:00:00Z)")
    p.add_argument("--setup",       action="store_true", help="Run one-time Page setup")
    p.add_argument("--page-id",     dest="page_id", help="Facebook Page ID (for --setup)")
    p.add_argument("--token",       help="User access token, or Page token with --page-token (for --setup)")
    p.add_argument("--page-token",  dest="page_token", action="store_true",
                   help="Treat --token as a Page access token (store as-is)")
    p.add_argument("--reset",       action="store_true", help="Delete stored credentials")
    a = p.parse_args()

    if a.reset:
        reset_auth()
        return

    if a.setup:
        if not a.page_id or not a.token:
            p.error("--setup requires --page-id and --token")
        setup(a.page_id, a.token, is_page_token=a.page_token)
        return

    if not a.project and not a.file:
        p.error("Provide --project or --file")

    title       = a.title or ""
    description = a.description or ""
    if a.project:
        try:
            from upload_instagram import _read_manifest, _build_caption
            manifest = _read_manifest(a.project)
            if not title:
                vi = manifest.get("video_info", {}) or {}
                title = vi.get("title") or manifest.get("title") or a.project
            if not description:
                description = _build_caption(manifest)
        except Exception as e:
            logger.warning("Could not read manifest: %s", e)

    file_path = a.file or _final_video_path(a.project)

    # Accept either a raw unix timestamp or an ISO 8601 string for --publish-at.
    sched_ts = None
    if a.publish_at:
        try:
            sched_ts = int(a.publish_at)
        except ValueError:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(a.publish_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            sched_ts = int(dt.timestamp())

    try:
        vid = upload_facebook(file_path, title=title, description=description, as_reel=a.reel,
                              thumb_offset_ms=a.cover_ms, scheduled_publish_time=sched_ts)
        print("\nVideo ID : " + vid)
    except Exception as e:
        logger.error("Upload failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
