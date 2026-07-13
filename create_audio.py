"""
create_audio.py
===============
Generates audio for every TTS scene in manifest["scenes"].

For each scene where audio.type == "tts" and audio.file_path is null:
  - Calls ElevenLabs with prosody context (prev/next TTS text)
  - Writes the MP3 to project/audio/
  - Fills audio.file_path, audio.duration_ms, scene.duration_ms

For SFX scenes: reads duration from the file (if possible) and fills
audio.duration_ms + scene.duration_ms.

Repetition scenes (flagged with _is_repetition: true) also get an
after_pause_ms field = duration_ms * _rep_pause_factor.

Reuses existing audio files — skips if audio.file_path is set and file exists.
Pass overwrite=True to force every TTS line to be re-synthesized regardless of
what already exists (the default, overwrite=False, only fills in what's missing).
"""

import io, json, logging, argparse, os, base64, tempfile
from pathlib import Path
from pydub import AudioSegment
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from utils_config import load_config
from utils_markup import strip_for_tts
from core import report_progress

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
load_dotenv()


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    """Atomically write manifest using a temp file + rename to prevent corruption."""
    tmp = manifest_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    tmp.replace(manifest_path)


def create_audio(project_name: str, overwrite: bool = False) -> None:
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    audio_dir     = project_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    eleven = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
    model  = cfg["elevenlabs_model"]
    fmt    = cfg["audio_format"]

    scenes = manifest["scenes"]

    # ── Build ordered list of TTS texts for prosody context ──────────────────
    # strip_for_tts removes -silent- spans entirely and strips _italic_/*bold* markers
    tts_texts = [
        strip_for_tts(s["audio"]["tts_text"])
        for s in scenes
        if s.get("audio") and s["audio"].get("type") == "tts"
    ]
    tts_scene_order = [
        i for i, s in enumerate(scenes)
        if s.get("audio") and s["audio"].get("type") == "tts"
    ]

    def _prosody(tts_pos: int) -> tuple[str | None, str | None]:
        """Return (prev_text, next_text) for a TTS scene at position tts_pos in tts_texts."""
        prev = tts_texts[tts_pos - 1] if tts_pos > 0 else None
        next_ = tts_texts[tts_pos + 1] if tts_pos + 1 < len(tts_texts) else None
        return prev, next_

    def _generate_tts(text: str, voice_id: str, filename: str,
                       prev_text: str | None, next_text: str | None,
                       force: bool = False) -> tuple[str, int]:
        out_path = audio_dir / filename
        if out_path.exists() and not force:
            logger.info(f"  Audio exists: {filename}")
            audio_bytes = out_path.read_bytes()
        else:
            logger.info(f"  Generating: {filename}")
            result = eleven.text_to_speech.convert_with_timestamps(
                text=text, voice_id=voice_id, model_id=model,
                output_format=fmt, previous_text=prev_text, next_text=next_text,
            )
            audio_bytes = base64.b64decode(result.audio_base_64)
            out_path.write_bytes(audio_bytes)
        seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
        return f"audio/{filename}", len(seg)

    def _sfx_duration(file_path_rel: str) -> int | None:
        """Try to read duration of an SFX file in ms."""
        full = cfg["assets_dir"].parent / file_path_rel
        if not full.exists():
            full = Path(file_path_rel)
        try:
            seg = AudioSegment.from_file(str(full))
            return len(seg)
        except Exception:
            return None

    # ── Process all scenes ────────────────────────────────────────────────────
    # Progress is measured over the TTS lines (the actual work); SFX/video/pause
    # scenes are skipped near-instantly and don't move the bar.
    tts_total = len(tts_scene_order)
    tts_pos = 0
    for scene in scenes:
        audio = scene.get("audio")
        if not audio:
            continue  # pause scene — duration already set

        atype = audio.get("type")

        # ── TTS ──
        if atype == "tts":
            prev_t, next_t = _prosody(tts_pos)
            tts_pos += 1
            report_progress(tts_pos, tts_total, f"Audio {tts_pos}/{tts_total}")

            if not (audio.get("tts_text") or "").strip():
                logger.warning(f"  [{scene['id']}] has no text yet — skipping.")
                continue

            if not overwrite and audio.get("file_path") and (project_path / audio["file_path"]).exists():
                logger.info(f"  [{scene['id']}] TTS exists, skipping.")
                continue

            # Derive filename from scene id
            filename = f"{scene['id']}.mp3"
            afile, dur_ms = _generate_tts(
                text      = strip_for_tts(audio["tts_text"]),
                voice_id  = audio["voice_id"],
                filename  = filename,
                prev_text = prev_t,
                next_text = next_t,
                force     = overwrite,
            )
            audio["file_path"]   = afile
            audio["duration_ms"] = dur_ms
            scene["duration_ms"] = dur_ms

            # After-pause for repetition scenes
            if scene.get("_is_repetition"):
                factor = scene.get("_rep_pause_factor", 1.3)
                scene["after_pause_ms"] = int(dur_ms * factor)

        # ── SFX ──
        elif atype == "sfx":
            if audio.get("duration_ms"):
                continue  # already measured
            dur_ms = _sfx_duration(audio.get("file_path", ""))
            if dur_ms:
                audio["duration_ms"] = dur_ms
                scene["duration_ms"] = dur_ms

        # ── Video clip ──
        elif atype == "video_clip":
            if audio.get("duration_ms"):
                continue
            try:
                from moviepy.editor import VideoFileClip
                vpath = cfg["assets_dir"].parent / audio.get("file_path", "")
                with VideoFileClip(str(vpath)) as clip:
                    dur_ms = int(clip.duration * 1000)
                audio["duration_ms"] = dur_ms
                scene["duration_ms"] = dur_ms
            except Exception as e:
                logger.warning(f"  Could not read video clip duration: {e}")

    _write_manifest(manifest_path, manifest)
    logger.info("Audio generation complete.")


def create_audio_single(project_name: str, scene_id: str) -> None:
    """
    Regenerate audio for a single TTS scene by scene ID.
    Prosody context (previous/next text) is derived from the surrounding TTS
    scenes in the manifest, so intonation still sounds natural.
    Always overwrites the existing audio file for that scene.
    """
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    audio_dir     = project_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    target = next((s for s in manifest["scenes"] if s["id"] == scene_id), None)
    if not target:
        raise ValueError(f"Scene '{scene_id}' not found in manifest")

    audio = target.get("audio")
    if not audio or audio.get("type") != "tts":
        raise ValueError(f"Scene '{scene_id}' is not a TTS scene (type={audio.get('type') if audio else None})")
    if not (audio.get("tts_text") or "").strip():
        raise ValueError(f"Scene '{scene_id}' has no text yet — edit the scene and add its German text first.")

    # Build the ordered list of TTS texts for prosody context
    tts_scenes = [
        s for s in manifest["scenes"]
        if s.get("audio") and s["audio"].get("type") == "tts"
    ]
    # strip_for_tts: remove -silent- spans, strip _italic_/*bold* markers
    tts_texts = [strip_for_tts(s["audio"]["tts_text"]) for s in tts_scenes]
    tts_pos   = next((i for i, s in enumerate(tts_scenes) if s["id"] == scene_id), None)

    prev_text = tts_texts[tts_pos - 1] if tts_pos and tts_pos > 0 else None
    next_text = tts_texts[tts_pos + 1] if tts_pos is not None and tts_pos + 1 < len(tts_texts) else None

    eleven = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
    model  = cfg["elevenlabs_model"]
    fmt    = cfg["audio_format"]

    filename = f"{scene_id}.mp3"
    out_path = audio_dir / filename

    logger.info(f"Regenerating audio for {scene_id} (prev={bool(prev_text)}, next={bool(next_text)}) …")
    result = eleven.text_to_speech.convert_with_timestamps(
        text          = strip_for_tts(audio["tts_text"]),
        voice_id      = audio["voice_id"],
        model_id      = model,
        output_format = fmt,
        previous_text = prev_text,
        next_text     = next_text,
    )
    audio_bytes = base64.b64decode(result.audio_base_64)
    out_path.write_bytes(audio_bytes)

    seg    = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    dur_ms = len(seg)

    audio["file_path"]   = f"audio/{filename}"
    audio["duration_ms"] = dur_ms
    target["duration_ms"] = dur_ms

    if target.get("_is_repetition"):
        factor = target.get("_rep_pause_factor", 1.3)
        target["after_pause_ms"] = int(dur_ms * factor)

    _write_manifest(manifest_path, manifest)

    # Invalidate the rendered video clip so the next render pass rebuilds it
    video_clip = project_path / "videos" / f"{scene_id}.mp4"
    if video_clip.exists():
        video_clip.unlink()
        logger.info(f"Deleted stale video clip: {video_clip.name}")

    logger.info(f"Audio for {scene_id} saved → {out_path} ({dur_ms} ms)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("project_name")
    p.add_argument("--scene-id", dest="scene_id", default=None)
    p.add_argument("--overwrite", action="store_true",
                   help="re-synthesize every TTS line, overwriting existing audio")
    a = p.parse_args()
    if a.scene_id:
        create_audio_single(a.project_name, a.scene_id)
    else:
        create_audio(a.project_name, overwrite=a.overwrite)


if __name__ == "__main__":
    main()
