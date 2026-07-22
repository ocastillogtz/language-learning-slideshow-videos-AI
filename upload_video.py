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

Authentication flow
-------------------
First run opens a browser for OAuth consent.
Credentials are cached in token.json and refreshed automatically.

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

    if TOKEN_FILE.exists():
        logger.debug("Loading cached credentials from %s", TOKEN_FILE)
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
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
            if not CLIENT_SECRET_FILE.exists():
                raise FileNotFoundError(
                    f"OAuth client secret not found: {CLIENT_SECRET_FILE}\n"
                    "Download it from Google Cloud Console → APIs & Services → Credentials."
                )
            logger.info("Opening browser for OAuth consent …")
            flow  = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

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
