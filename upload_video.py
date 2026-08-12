"""
upload_video.py
===============
Upload the final video of a pipeline project to YouTube.

Setup (one-time)
----------------
1. Google Cloud Console → create a project
2. Enable "YouTube Data API v3"
3. Create OAuth 2.0 Client ID → Desktop Application
4. Download JSON → save as  client_secret.json  next to this script

How the connection works (OAuth 2.0, "installed app" flow)
----------------------------------------------------------
YouTube does NOT use a simple API key. It uses OAuth 2.0, where the app acts
*on your behalf* after you grant it consent in a browser. Two secrets are involved,
and it helps to keep them straight:

1. The OAuth *client* (app identity) — a client_id + client_secret that identify
   THIS application to Google. They are the same for every user of the app and are
   NOT personal. They come either from GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in
   .env, or from a downloaded client_secret.json. (see `_build_oauth_flow`)

2. The *user* credentials (token) — proof that YOU personally clicked "Allow".
   These are obtained by the browser consent flow the first time and then cached in
   token.json. They contain a short-lived `access_token` plus a long-lived
   `refresh_token`; the library silently uses the refresh_token to mint new access
   tokens when the old one expires, so you only consent once. (see `authenticate`)

`SCOPES` lists exactly what the app is allowed to do — here only `youtube.upload`.
A token is limited to the scopes you consented to: an upload-only token can push a
video but cannot even read your channel name (that needs `youtube.readonly`). This
is why the connection test (`get_channel_info`) treats a 403 on channels.list as
"valid but scope-limited" rather than a failure.

Usage
-----
# Upload from manifest (reads title, description, tags automatically)
python upload_video.py --project my_project

# Override fields manually
python upload_video.py --project my_project --title "Im Café: Deutsch B1" --privacy public

# Explicit file path (bypasses manifest lookup)
python upload_video.py --file projects/my_project/final_my_project.mp4 --title "..."

pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SCOPES             = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE         = Path("token.json")
CLIENT_SECRET_FILE = Path("client_secret.json")

# Resumable upload retry settings
MAX_RETRIES        = 5
RETRY_EXCEPTIONS   = (Exception,)     # broad — includes network errors


# =========================
# AUTHENTICATION
# =========================
def _build_oauth_flow() -> InstalledAppFlow:
    """Build the OAuth consent flow.

    Prefers GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET from the environment (.env,
    hybrid secret model); falls back to the downloaded client_secret.json file.
    """
    client_id     = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        logger.debug("Building OAuth flow from GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (.env)")
        client_config = {
            "installed": {
                "client_id":     client_id,
                "client_secret": client_secret,
                "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
                "token_uri":     "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        return InstalledAppFlow.from_client_config(client_config, SCOPES)

    if not CLIENT_SECRET_FILE.exists():
        raise FileNotFoundError(
            f"OAuth client not configured: set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET "
            f"in .env, or place {CLIENT_SECRET_FILE} next to this script.\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )
    return InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)


def get_channel_info() -> dict:
    """Return {title, id} for the authenticated channel — for the connection test.

    Non-interactive: uses only the cached token.json (refreshing it if possible)
    and NEVER launches the browser consent flow. Raises if not yet authenticated.
    """
    if not TOKEN_FILE.exists():
        raise RuntimeError(
            "Not authenticated — no token.json yet. Run a YouTube upload once to "
            "complete the browser consent flow."
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
        else:
            raise RuntimeError("Stored credentials are invalid — re-authenticate by uploading once.")

    youtube = build("youtube", "v3", credentials=creds)
    # The upload token only carries the youtube.upload scope, which is NOT allowed
    # to read channels.list. A 403 there therefore means the token is valid but
    # scope-limited — still a successful connection, just without the channel name.
    try:
        resp  = youtube.channels().list(part="snippet", mine=True).execute()
        items = resp.get("items", [])
        if items:
            snip = items[0].get("snippet", {})
            return {"title": snip.get("title", ""), "id": items[0].get("id", ""),
                    "scope_limited": False}
    except HttpError as e:
        if e.resp.status != 403:
            raise
    return {"title": "", "id": "", "scope_limited": True}


def authenticate() -> Credentials:
    """
    Return valid OAuth2 credentials, running the browser flow if needed.
    Cached in token.json and auto-refreshed on expiry.

    If the stored refresh token is rejected by Google (invalid_grant — common
    when the OAuth app is in Testing mode and the 7-day token lifetime has
    passed, or the token was manually revoked), the stale token.json is
    deleted and a fresh browser consent flow is started automatically.
    """
    creds: Optional[Credentials] = None

    # Step 1 — reuse the cached user token if we have one. token.json holds the
    # access_token + refresh_token from a previous consent, so we don't prompt again.
    if TOKEN_FILE.exists():
        logger.debug("Loading cached credentials from %s", TOKEN_FILE)
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        # Step 2 — the access_token expired but we still hold a refresh_token:
        # exchange it for a fresh access_token silently (no browser, no user action).
        if creds and creds.expired and creds.refresh_token:
            try:
                logger.info("Refreshing expired credentials …")
                creds.refresh(Request())
            except RefreshError as exc:
                # invalid_grant or similar — token has been revoked or expired
                logger.warning(
                    "Token refresh failed (%s) — deleting stale token and "
                    "re-running OAuth consent flow.", exc
                )
                TOKEN_FILE.unlink(missing_ok=True)
                creds = None   # fall through to browser flow below

        if not creds or not creds.valid:
            # Step 3 — no usable token at all: run the interactive consent flow.
            # run_local_server spins up a temporary localhost web server, opens the
            # browser to Google's consent screen, and captures the redirect that
            # carries the authorization code — which the library swaps for tokens.
            logger.info("Opening browser for OAuth consent …")
            flow  = _build_oauth_flow()
            creds = flow.run_local_server(port=0)

        # Persist whatever we ended up with (refreshed or freshly consented) so the
        # next run skips straight back to Step 1.
        TOKEN_FILE.write_text(creds.to_json())
        logger.debug("Credentials saved to %s", TOKEN_FILE)

    return creds


def reset_auth() -> None:
    """Delete the cached token so the next upload triggers a fresh OAuth flow."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        logger.info("Deleted %s — next upload will re-authenticate.", TOKEN_FILE)
    else:
        logger.info("No token file found — nothing to reset.")


# =========================
# MANIFEST HELPERS
# =========================
def _read_manifest(project_name: str) -> dict:
    """Load the project manifest from the projects/ directory."""
    # Try config.ini first; fall back to default path
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read("config.ini")
        projects_dir = Path(cfg["paths"]["projects_dir"])
    except Exception:
        projects_dir = Path("projects")

    path = projects_dir / project_name / "project_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _final_video_path(project_name: str, manifest: dict) -> Path:
    """Return the expected path of the assembled final video."""
    try:
        import configparser
        cfg = configparser.ConfigParser()
        cfg.read("config.ini")
        projects_dir = Path(cfg["paths"]["projects_dir"])
    except Exception:
        projects_dir = Path("projects")

    return projects_dir / project_name / f"final_{project_name}.mp4"


def _build_metadata(manifest: dict) -> tuple[str, str, list[str]]:
    """
    Extract title, description, and tags from the project manifest.

    Supports both the current nested format (video_info / generation_config)
    and the legacy flat format for older projects.

    Returns (title, description, tags)
    """
    # ── nested (current) format ──────────────────────────────────────────────
    vi  = manifest.get("video_info") or {}
    gc  = manifest.get("generation_config") or {}

    # ── field resolution: nested first, fall back to flat legacy keys ────────
    title    = vi.get("title")    or manifest.get("title")    or "German Learning Video"
    insights = vi.get("insights") or manifest.get("insights", "") or ""
    location = gc.get("location_key") or manifest.get("location-key", "") or ""
    style    = (manifest.get("project_metadata") or {}).get("project_type_key") \
               or manifest.get("style", "") or ""

    # Characters: new format stores them as a list of strings; legacy as list of dicts
    raw_chars = gc.get("characters") or manifest.get("characters", [])
    if raw_chars and isinstance(raw_chars[0], dict):
        chars = [c["name"] for c in raw_chars]
    else:
        chars = [c for c in raw_chars if isinstance(c, str)]
    chars_str = " & ".join(chars) if chars else ""

    # Build a rich description
    desc_parts = []
    if chars_str:
        desc_parts.append(f"Characters: {chars_str}")
    if location:
        desc_parts.append(f"Location: {location}")
    if style:
        desc_parts.append(f"Style: {style}")
    if insights:
        desc_parts.append("")
        desc_parts.append(insights[:800])   # YouTube description limit is 5000 chars

    desc_parts += [
        "",
        "Learn German naturally through authentic dialogue.",
        "#germanlearning #deutschlernen #learnGerman",
    ]
    description = "\n".join(desc_parts)

    # Tags from manifest + automatic language tags
    raw_tags = vi.get("tags") or manifest.get("tags", "") or ""
    # raw_tags is like "#germanlearning #deutschlernen ..." — strip # and split
    auto_tags = [t.lstrip("#") for t in raw_tags.split() if t.startswith("#")]
    extra_tags = ["german", "deutsch", "learnGerman", "deutschlernen", "shorts",
                  "languagelearning", "germanlearning"]
    tags = list(dict.fromkeys(auto_tags + extra_tags))   # deduplicate, preserve order

    return title, description, tags


# =========================
# UPLOAD
# =========================
def upload_video(
    file_path: Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str,
    category_id: str = "22",   # 22 = People & Blogs (common for Shorts)
    publish_at: Optional[str] = None,
    made_for_kids: bool = False,
) -> str:
    """
    Upload *file_path* to YouTube and return the video ID.

    Implements chunked resumable upload with retry on transient errors.

    If *publish_at* (an RFC 3339 UTC timestamp, e.g. "2026-07-01T17:00:00Z")
    is supplied, the video is uploaded as private and YouTube automatically
    flips it to public at that time. The YouTube API requires privacyStatus to
    be "private" when publishAt is set, so privacy is forced accordingly.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Video file not found: {file_path}")

    logger.info("Authenticating …")
    creds   = authenticate()
    youtube = build("youtube", "v3", credentials=creds)

    status: dict = {
        "privacyStatus":            "private" if publish_at else privacy,
        "selfDeclaredMadeForKids":  made_for_kids,
    }
    if publish_at:
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title":       title[:100],         # YouTube title limit
            "description": description,
            "tags":        tags[:500],           # API limit
            "categoryId":  category_id,
        },
        "status": status,
    }

    logger.info("Starting upload: %s  (%s MB)", file_path.name,
                f"{file_path.stat().st_size / 1e6:.1f}")

    media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True)

    insert_req = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response: Optional[dict] = None
    error:    Optional[Exception] = None
    retry     = 0

    while response is None:
        try:
            status, response = insert_req.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.info("  Upload: %d%%", pct)
            error = None
            retry = 0
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and retry < MAX_RETRIES:
                wait = 2 ** retry
                logger.warning("HTTP %s — retrying in %ds …", e.resp.status, wait)
                time.sleep(wait)
                retry += 1
            else:
                raise
        except Exception as e:
            if retry < MAX_RETRIES:
                wait = 2 ** retry
                logger.warning("Upload error (%s) — retrying in %ds …", e, wait)
                time.sleep(wait)
                retry += 1
                error = e
            else:
                raise RuntimeError(f"Upload failed after {MAX_RETRIES} retries") from e

    video_id: str = response["id"]
    logger.info("✓ Upload complete — https://youtu.be/%s", video_id)
    return video_id


# =========================
# CLI
# =========================
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload the final project video to YouTube.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Let manifest supply title/description/tags
  python upload_video.py --project my_project

  # Override title, upload as public
  python upload_video.py --project my_project --title "Im Café: Deutsch B1" --privacy public

  # Explicit file path
  python upload_video.py --file projects/x/final_x.mp4 --title "Title" --privacy private
""",
    )
    parser.add_argument("--project",  help="Project name (reads manifest for metadata)")
    parser.add_argument("--file",     type=Path, help="Explicit video file path")
    parser.add_argument("--title",    help="Override video title")
    parser.add_argument("--description", help="Override video description")
    parser.add_argument("--privacy",  default="private",
                        choices=["public", "private", "unlisted"])
    parser.add_argument("--publish-at", dest="publish_at",
                        help="Schedule release: RFC 3339 UTC timestamp, "
                             "e.g. 2026-07-01T17:00:00Z (forces private until then)")
    parser.add_argument("--made-for-kids", dest="made_for_kids", action="store_true",
                        help="Mark the video as made for kids")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level))

    if not args.project and not args.file:
        parser.error("Provide --project or --file")

    # ---- Resolve file path and metadata ----
    title       = args.title or "German Learning Video"
    description = args.description or ""
    tags: list[str] = ["shorts", "german", "deutschlernen"]

    if args.project:
        try:
            manifest    = _read_manifest(args.project)
            t, d, tg    = _build_metadata(manifest)
            title       = args.title or t
            description = args.description or d
            tags        = tg
        except FileNotFoundError as e:
            logger.warning("Could not read manifest: %s — using defaults", e)

    file_path = args.file or _final_video_path(args.project, manifest if args.project else {})

    try:
        vid_id = upload_video(
            file_path     = file_path,
            title         = title,
            description   = description,
            tags          = tags,
            privacy       = args.privacy,
            publish_at    = args.publish_at,
            made_for_kids = args.made_for_kids,
        )
        print(f"\nVideo ID : {vid_id}")
        print(f"Watch    : https://youtu.be/{vid_id}")
        print(f"Studio   : https://studio.youtube.com/video/{vid_id}/edit")
    except Exception as e:
        logger.error("Upload failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
