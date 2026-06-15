"""
check_dependencies.py
=====================
Verifies that everything the German Learning Video tool needs is installed
(Windows-only tool).

Checks, in order:
  * Python version
  * Required Python packages (without importing heavy modules)
  * External binaries: ffmpeg, ffprobe, ImageMagick
  * ImageMagick Pango delegate  (needed for annotated, method="pango" subtitles)
  * Playwright Chromium browser (needed for HTML annotation rendering)
  * Configured subtitle fonts   (Calibri / Arial by default)

Run it directly:

    python check_dependencies.py

or import and call:

    from check_dependencies import check_dependencies
    ok = check_dependencies()          # True if every REQUIRED check passed
"""

from __future__ import annotations

import configparser
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Status levels -------------------------------------------------------------
OK, WARN, FAIL = "OK", "WARN", "FAIL"
_SYMBOL = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}

# (import_name, pip_name) for every third-party package the code imports.
REQUIRED_PACKAGES = [
    ("moviepy", "moviepy==1.0.3"),
    ("numpy", "numpy<2.0"),
    ("PIL", "Pillow"),
    ("imageio_ffmpeg", "imageio-ffmpeg"),
    ("playwright", "playwright"),
    ("pydub", "pydub"),
    ("dotenv", "python-dotenv"),
    ("requests", "requests"),
    ("openai", "openai"),
    ("elevenlabs", "elevenlabs"),
    ("fal_client", "fal-client"),
    ("flask", "Flask"),
    ("googleapiclient", "google-api-python-client"),
    ("google_auth_oauthlib", "google-auth-oauthlib"),
    ("google.auth", "google-auth-httplib2"),
]

MIN_PY = (3, 9)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _run(cmd):
    """Run a command, return (returncode, combined_output) or (None, '') on error."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return None, ""


def _module_available(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _config_imagemagick() -> str:
    """Read the imagemagick path from config.ini ([tools] imagemagick), if present."""
    cfg_path = Path(__file__).resolve().parent / "config.ini"
    if not cfg_path.exists():
        return ""
    parser = configparser.ConfigParser()
    try:
        parser.read(cfg_path, encoding="utf-8")
        return parser.get("tools", "imagemagick", fallback="").strip()
    except configparser.Error:
        return ""


def _find_magick():
    """
    Locate an ImageMagick binary. Returns (path_or_cmd, source) where source is
    'config', 'PATH', or '' if not found.
    """
    configured = _config_imagemagick()
    if configured and Path(configured).exists():
        return configured, "config"
    for cmd in ("magick", "convert"):
        found = shutil.which(cmd)
        if found:
            return found, "PATH"
    # configured but missing -> report it so the user knows to fix config.ini
    if configured:
        return configured, "config-missing"
    return "", ""


# --------------------------------------------------------------------------
# individual checks  ->  each returns (name, status, detail)
# --------------------------------------------------------------------------
def _check_python():
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= MIN_PY:
        return ("Python interpreter", OK, f"{ver}  ({sys.executable})")
    return ("Python interpreter", FAIL,
            f"{ver} — need >= {MIN_PY[0]}.{MIN_PY[1]}")


def _check_packages():
    rows = []
    for import_name, pip_name in REQUIRED_PACKAGES:
        if _module_available(import_name):
            rows.append((f"package: {pip_name}", OK, import_name))
        else:
            rows.append((f"package: {pip_name}", FAIL,
                         f"cannot import '{import_name}'  ->  pip install {pip_name}"))
    return rows


def _check_ffmpeg():
    rows = []
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if path:
            rc, out = _run([tool, "-version"])
            ver = out.splitlines()[0] if out else ""
            rows.append((f"{tool} (on PATH)", OK, ver or path))
        else:
            rows.append((f"{tool} (on PATH)", FAIL,
                         f"not found on PATH — required for video/audio assembly"))
    return rows


def _check_imagemagick():
    rows = []
    magick, source = _find_magick()
    if not magick:
        rows.append(("ImageMagick", FAIL,
                     "not found — install it and set [tools] imagemagick in config.ini"))
        return rows, None

    if source == "config-missing":
        rows.append(("ImageMagick", FAIL,
                     f"config.ini path does not exist: {magick}\n"
                     "        set it to the installed magick.exe, or to 'magick' if it is on PATH"))
        return rows, None

    rc, out = _run([magick, "-version"])
    if rc is None:
        rows.append(("ImageMagick", FAIL, f"could not run: {magick}"))
        return rows, None
    ver = out.splitlines()[0] if out else magick
    note = f"{ver}  (via {source})"
    if source == "PATH" and _config_imagemagick() and not Path(_config_imagemagick()).exists():
        note += "\n        NOTE: config.ini imagemagick path is stale; set it to 'magick'"
    rows.append(("ImageMagick", OK, note))

    # Pango delegate (needed for annotated subtitles, method="pango")
    rc, fmt = _run([magick, "-list", "format"])
    if rc is not None and "PANGO" in fmt.upper():
        rows.append(("ImageMagick Pango delegate", OK, "annotated subtitles supported"))
    else:
        rows.append(("ImageMagick Pango delegate", WARN,
                     "PANGO not listed — annotated (method='pango') subtitles will fail; "
                     "plain subtitles still work"))
    return rows, magick


def _check_playwright_chromium():
    if not _module_available("playwright"):
        return ("Playwright Chromium", WARN,
                "playwright package missing — HTML annotation rendering disabled")
    # Default Windows install location for the browser binaries.
    base = os.environ.get("LOCALAPPDATA", "")
    pw_dir = Path(base) / "ms-playwright" if base else None
    if pw_dir and pw_dir.exists() and any(pw_dir.glob("chromium-*")):
        return ("Playwright Chromium", OK, str(pw_dir))
    return ("Playwright Chromium", WARN,
            "browser not installed — run:  python -m playwright install chromium")


def _check_fonts(magick):
    """Best-effort font check via ImageMagick's font list."""
    wanted = ("Calibri", "Arial")
    if not magick:
        return ("Fonts (Calibri / Arial)", WARN,
                "cannot verify (ImageMagick missing)")
    rc, out = _run([magick, "-list", "font"])
    if rc is None or not out:
        return ("Fonts (Calibri / Arial)", WARN, "could not query ImageMagick font list")
    up = out.upper()
    missing = [f for f in wanted if f.upper() not in up]
    if not missing:
        return ("Fonts (Calibri / Arial)", OK, "both available")
    return ("Fonts (Calibri / Arial)", WARN,
            f"not found: {', '.join(missing)} — subtitles will fall back to a default font. "
            "Install the font(s) or change the font names in config.ini")


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------
def check_dependencies(verbose: bool = True) -> bool:
    """
    Run every dependency check. Prints a report when verbose=True.
    Returns True only if no REQUIRED check failed (WARN does not fail the run).
    """
    sections = []

    sections.append(("Python", [_check_python()]))
    sections.append(("Python packages", _check_packages()))

    external = []
    external += _check_ffmpeg()
    im_rows, magick = _check_imagemagick()
    external += im_rows
    sections.append(("External tools", external))

    optional = [
        _check_playwright_chromium(),
        _check_fonts(magick),
    ]
    sections.append(("Annotation / rendering (optional)", optional))

    n_fail = n_warn = 0
    if verbose:
        print("=" * 64)
        print(" Dependency check — German Learning Video tool")
        print("=" * 64)

    for title, rows in sections:
        if verbose:
            print(f"\n{title}")
            print("-" * len(title))
        for name, status, detail in rows:
            if status == FAIL:
                n_fail += 1
            elif status == WARN:
                n_warn += 1
            if verbose:
                print(f"  {_SYMBOL[status]} {name}: {detail}")

    ok = n_fail == 0
    if verbose:
        print("\n" + "=" * 64)
        if ok and n_warn == 0:
            print(" RESULT: all dependencies satisfied.")
        elif ok:
            print(f" RESULT: required dependencies OK, {n_warn} optional warning(s).")
        else:
            print(f" RESULT: {n_fail} required dependency(ies) MISSING, {n_warn} warning(s).")
            print(" Run install_dependencies.bat, then re-run this check.")
        print("=" * 64)
    return ok


if __name__ == "__main__":
    sys.exit(0 if check_dependencies() else 1)
