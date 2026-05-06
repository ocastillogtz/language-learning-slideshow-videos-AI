"""
upload_instagram.py
===================
Upload the final project video to Instagram as a Reel.

SETUP (one-time)
----------------
1. Go to https://developers.facebook.com and create an App
   (type: "Business", then add "Instagram Graph API" product)

2. In Graph API Explorer (https://developers.facebook.com/tools/explorer/):
   - Select your App
   - Leave "User or Page" as "Get Token" (user token, not a page token)
   - Generate a User Access Token with these permissions:
       instagram_basic, instagram_content_publish, pages_show_list
   - Copy the short-lived token

3. Enter App ID, App Secret, and token in Step 7 of the pipeline UI.
   The backend exchanges it for a 60-day long-lived token automatically.

USAGE
-----
    python upload_instagram.py --project my_project
    python upload_instagram.py --project my_project --caption "Im Cafe"

NOTES
-----
- Videos publish as Reels (vertical 9:16 recommended)
- Processing can take 30-120 seconds after upload
- pip install requests
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

GRAPH_BASE    = "https://graph.facebook.com/v25.0"
UPLOAD_BASE   = "https://rupload.facebook.com/ig-api-upload/v25.0"
CREDS_FILE    = Path("instagram_creds.json")
POLL_INTERVAL = 10
POLL_TIMEOUT  = 300
CHUNK_SIZE    = 10 * 1024 * 1024


# =============================================================================
# CREDENTIALS
# =============================================================================

def _load_creds() -> dict:
    if not CREDS_FILE.exists():
        raise FileNotFoundError(
            "instagram_creds.json not found.\n"
            "Use Step 7 in the pipeline UI to save your credentials."
        )
    with open(CREDS_FILE) as f:
        return json.load(f)


def _save_creds(creds: dict) -> None:
    with open(CREDS_FILE, "w") as f:
        json.dump(creds, f, indent=2)
    logger.debug("Credentials saved to %s", CREDS_FILE)


def _exchange_for_long_lived(app_id: str, app_secret: str, short_token: str) -> dict:
    """
    Exchange a short-lived user token for a long-lived one (60 days).
    If the exchange returns 400 (e.g. token is already long-lived),
    fall back to inspecting it via /debug_token and using it as-is.
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
            params={
                "input_token":  short_token,
                "access_token": str(app_id) + "|" + str(app_secret),
            },
            timeout=30,
        )
        if debug.ok:
            ddata = debug.json().get("data", {})
            expires_at = ddata.get("expires_at", 0)
            if expires_at == 0:
                expires_in = 60 * 86400
            else:
                expires_in = max(0, int(expires_at - time.time()))
            logger.info("debug_token: expires_in=%ds, scopes=%s", expires_in, ddata.get("scopes"))
            return {"access_token": short_token, "expires_in": expires_in}
        else:
            logger.warning("debug_token also failed: %s", debug.text)

        raise RuntimeError(
            "Token exchange failed (400). Facebook said: " + str(fb_err) + "\n"
            "Make sure you are using a User Access Token (not a Page token) from the Graph API Explorer.\n"
            "In the Explorer, leave 'User or Page' as 'Get Token' -- do not select a specific Page."
        )

    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError("Token exchange failed: " + str(data["error"]))
    return data


def _refresh_token(creds: dict) -> dict:
    logger.info("Refreshing Instagram long-lived token ...")
    return _exchange_for_long_lived(creds["app_id"], creds["app_secret"], creds["access_token"])


def _lookup_ig_user_id(access_token: str) -> str:
    """Find the Instagram Creator/Business account ID linked to the Facebook user."""
    me = requests.get(
        GRAPH_BASE + "/me",
        params={"access_token": access_token, "fields": "id,name"},
        timeout=15,
    )
    me.raise_for_status()
    logger.info("Logged in as: %s", me.json().get("name"))

    pages_r = requests.get(
        GRAPH_BASE + "/me/accounts",
        params={"access_token": access_token, "fields": "id,name,instagram_business_account"},
        timeout=15,
    )
    pages_r.raise_for_status()
    pages = pages_r.json().get("data", [])
    logger.info("Found %d Facebook Page(s)", len(pages))

    for page in pages:
        iga = page.get("instagram_business_account")
        if iga:
            logger.info("Found IG account %s on page '%s'", iga["id"], page["name"])
            return iga["id"]

    raise RuntimeError(
        "No Instagram Business/Creator account found linked to your Facebook Pages.\n"
        "Make sure your Instagram account is connected to a Facebook Page:\n"
        "  Instagram Settings -> Account -> Linked Accounts -> Facebook"
    )


def setup(app_id: str, app_secret: str, short_token: str, ig_user_id: str = None) -> None:
    """One-time setup: exchange token, look up IG User ID, save creds."""
    logger.info("Exchanging for long-lived token ...")
    ll = _exchange_for_long_lived(app_id, app_secret, short_token)
    access_token = ll["access_token"]
    expires_in   = ll.get("expires_in", 5184000)
    expiry_ts    = int(time.time()) + int(expires_in)

    if ig_user_id:
        logger.info("Using manually provided Instagram User ID: %s", ig_user_id)
    else:
        logger.info("Looking up Instagram User ID ...")
        ig_user_id = _lookup_ig_user_id(access_token)

    creds = {
        "app_id":       app_id,
        "app_secret":   app_secret,
        "access_token": access_token,
        "expiry_ts":    expiry_ts,
        "ig_user_id":   ig_user_id,
    }
    _save_creds(creds)
    days_left = (expiry_ts - int(time.time())) // 86400
    logger.info("Setup complete. IG User ID: %s  Token valid for ~%d days.", ig_user_id, days_left)


def get_valid_token() -> tuple:
    """Return (access_token, ig_user_id), refreshing the token if it will expire within 7 days."""
    creds = _load_creds()
    days_left = (creds["expiry_ts"] - int(time.time())) // 86400

    if days_left < 7:
        logger.info("Token expires in %d days -- refreshing now ...", days_left)
        ll = _refresh_token(creds)
        creds["access_token"] = ll["access_token"]
        creds["expiry_ts"]    = int(time.time()) + int(ll.get("expires_in", 5184000))
        _save_creds(creds)

    return creds["access_token"], creds["ig_user_id"]


def reset_auth() -> None:
    if CREDS_FILE.exists():
        CREDS_FILE.unlink()
        logger.info("Deleted %s", CREDS_FILE)
    else:
        logger.info("No credentials file found -- nothing to reset.")


# =============================================================================
# UPLOAD
# =============================================================================

def _create_reel_container(ig_user_id: str, token: str, caption: str, share_to_feed: bool) -> tuple:
    """Step 1: Create a Reel media container. Returns (container_id, upload_uri)."""
    r = requests.post(
        GRAPH_BASE + "/" + ig_user_id + "/media",
        params={
            "access_token":  token,
            "media_type":    "REELS",
            "upload_type":   "resumable",
            "caption":       caption,
            "share_to_feed": "true" if share_to_feed else "false",
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError("Container creation failed: " + str(data["error"]))
    return data["id"], data["uri"]


def _upload_file(upload_uri: str, file_path: Path, token: str) -> None:
    """Step 2: Upload video in chunks to the resumable upload URI."""
    file_size = file_path.stat().st_size
    logger.info("Uploading %s (%.1f MB) ...", file_path.name, file_size / 1e6)

    with open(file_path, "rb") as f:
        uploaded = 0
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            headers = {
                "Authorization": "OAuth " + token,
                "offset":        str(uploaded),
                "file_size":     str(file_size),
                "Content-Type":  "application/octet-stream",
            }
            r = requests.post(upload_uri, headers=headers, data=chunk, timeout=120)
            r.raise_for_status()
            uploaded += len(chunk)
            logger.info("  Upload: %d%%  (%d / %d bytes)", int(uploaded / file_size * 100), uploaded, file_size)


def _poll_until_ready(container_id: str, token: str) -> None:
    """Step 3: Poll container status until FINISHED."""
    logger.info("Waiting for Instagram to process video ...")
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        r = requests.get(
            GRAPH_BASE + "/" + container_id,
            params={"access_token": token, "fields": "status_code,status"},
            timeout=15,
        )
        r.raise_for_status()
        data   = r.json()
        status = data.get("status_code", "")
        logger.info("  Container status: %s", status)
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError("Container processing failed: " + str(data.get("status", status)))
        time.sleep(POLL_INTERVAL)
    raise TimeoutError("Instagram container processing timed out after %ds" % POLL_TIMEOUT)


def _publish_container(ig_user_id: str, container_id: str, token: str) -> str:
    """Step 4: Publish the finished container. Returns the media ID."""
    r = requests.post(
        GRAPH_BASE + "/" + ig_user_id + "/media_publish",
        params={"access_token": token, "creation_id": container_id},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError("Publish failed: " + str(data["error"]))
    return data["id"]


def upload_instagram(file_path: Path, caption: str = "", share_to_feed: bool = True) -> str:
    """Full pipeline: create container -> upload -> poll -> publish. Returns media ID."""
    if not file_path.exists():
        raise FileNotFoundError("Video file not found: " + str(file_path))

    token, ig_user_id = get_valid_token()
    logger.info("Creating Reel container for user %s ...", ig_user_id)
    container_id, upload_uri = _create_reel_container(ig_user_id, token, caption, share_to_feed)
    logger.info("Container ID: %s", container_id)

    _upload_file(upload_uri, file_path, token)
    _poll_until_ready(container_id, token)

    logger.info("Publishing Reel ...")
    media_id = _publish_container(ig_user_id, container_id, token)
    logger.info("Reel published! Media ID: %s", media_id)
    logger.info("View at: https://www.instagram.com/p/%s/", media_id)
    return media_id


# =============================================================================
# MANIFEST HELPERS
# =============================================================================

def _read_manifest(project_name: str) -> dict:
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read("config.ini")
        projects_dir = Path(cfg["paths"]["projects_dir"])
    except Exception:
        projects_dir = Path("projects")
    path = projects_dir / project_name / "project_manifest.json"
    if not path.exists():
        raise FileNotFoundError("Manifest not found: " + str(path))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _final_video_path(project_name: str) -> Path:
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read("config.ini")
        projects_dir = Path(cfg["paths"]["projects_dir"])
    except Exception:
        projects_dir = Path("projects")
    return projects_dir / project_name / ("final_" + project_name + ".mp4")


def _build_caption(manifest: dict) -> str:
    vi   = manifest.get("video_info", {}) or {}
    gen  = manifest.get("generation_config", {}) or {}

    title    = vi.get("title") or manifest.get("title") or ""
    insights = vi.get("insights", "") or ""
    level    = gen.get("level", "") or ""
    location = gen.get("location_key", "") or manifest.get("location-key", "") or ""

    raw_tags = (vi.get("tags", "") or manifest.get("tags", "") or "")
    hashtags = " ".join(
        t if t.startswith("#") else "#" + t
        for t in raw_tags.replace(",", " ").split()
        if t.strip()
    )
    extra = "#germanlearning #deutschlernen #learngerman #shorts #deutsch"
    if level:
        extra += " #" + level.lower()

    parts = []
    if title:
        parts.append(title)
    if location:
        parts.append("Ort: " + location)
    if insights:
        parts.append("")
        parts.append(insights[:500])
    parts.append("")
    parts.append(hashtags + " " + extra if hashtags else extra)
    return "\n".join(parts).strip()


# =============================================================================
# CLI
# =============================================================================

def main():
    p = argparse.ArgumentParser(description="Upload a project video to Instagram as a Reel.")
    p.add_argument("--project",    help="Project name (reads manifest for caption)")
    p.add_argument("--file",       type=Path, help="Explicit video file path")
    p.add_argument("--caption",    help="Override caption text")
    p.add_argument("--no-feed",    action="store_true", help="Do not share to main feed")
    p.add_argument("--setup",      action="store_true", help="Run one-time token setup")
    p.add_argument("--app-id",     dest="app_id",     help="Facebook App ID (for --setup)")
    p.add_argument("--app-secret", dest="app_secret", help="Facebook App Secret (for --setup)")
    p.add_argument("--token",      help="Short-lived access token (for --setup)")
    p.add_argument("--reset",      action="store_true", help="Delete stored credentials")
    a = p.parse_args()

    if a.reset:
        reset_auth()
        return

    if a.setup:
        if not all([a.app_id, a.app_secret, a.token]):
            p.error("--setup requires --app-id, --app-secret, and --token")
        setup(a.app_id, a.app_secret, a.token)
        return

    if not a.project and not a.file:
        p.error("Provide --project or --file")

    manifest = {}
    if a.project:
        try:
            manifest = _read_manifest(a.project)
        except FileNotFoundError as e:
            logger.warning("Could not read manifest: %s", e)

    file_path = a.file or _final_video_path(a.project)
    caption   = a.caption or _build_caption(manifest)

    try:
        media_id = upload_instagram(file_path, caption=caption, share_to_feed=not a.no_feed)
        print("\nMedia ID : " + media_id)
    except Exception as e:
        logger.error("Upload failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
