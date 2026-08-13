"""
assemble_video.py
=================
Concatenates per-scene clips into the final video with optional background audio,
speed adjustment, and branding clip (intro/outro).
"""

import json
import logging
import argparse
import subprocess
import tempfile
import os
from pathlib import Path
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeAudioClip,
    concatenate_videoclips, concatenate_audioclips,
)
from moviepy.config import change_settings
from utils_config import load_config, load_background_audio_index

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def assemble_video(
    project_name,
    bg_audio_name="office",
    overwrite=False,
    speed_factor=None,
    branding_file=None,
    branding_mode="none",
    bg_audio_gain_db=0.0,
):
    cfg          = load_config()
    assets_dir   = cfg["assets_dir"]
    project_path = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"

    if speed_factor is None:
        speed_factor = cfg.get("speed_factor", 1.0)
    speed_factor = float(speed_factor)

    if cfg.get("imagemagick"):
        change_settings({"IMAGEMAGICK_BINARY": cfg["imagemagick"]})

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    videos_dir = project_path / "videos"
    out_path   = project_path / ("final_" + project_name + ".mp4")

    if out_path.exists() and not overwrite:
        logger.info("Output exists: %s -- use --overwrite to regenerate", out_path)
        return

    # Collect per-scene clips in scene order
    clip_paths = []
    for scene in manifest["scenes"]:
        p = videos_dir / (scene["id"] + ".mp4")
        if p.exists():
            clip_paths.append(p)
        else:
            logger.warning("Missing clip: %s -- skipping", scene["id"])

    if not clip_paths:
        raise RuntimeError("No clips found -- run create_video first")

    logger.info("Assembling %d clips ...", len(clip_paths))
    # Concatenate per-scene clips with FFmpeg (gapless; trims AAC priming and pads
    # short audio tails with real silence) instead of MoviePy, which otherwise
    # repeats the last audio buffer at each clip boundary -> audible glitch.
    concat_tmp = project_path / ("_concat_" + project_name + ".mp4")
    ffmpeg_concat_scenes(clip_paths, concat_tmp, fps=cfg["fps"])
    content = clamp_to_video_stream(VideoFileClip(str(concat_tmp)), concat_tmp, cfg["fps"])

    # Background audio
    bg_audio_path = _resolve_bg_audio(bg_audio_name, assets_dir)

    if bg_audio_path and bg_audio_path.exists():
        logger.info("Background audio: %s", bg_audio_path.name)
        bg_clip   = AudioFileClip(str(bg_audio_path))
        repeats   = int(content.duration / bg_clip.duration) + 2
        bg_looped = concatenate_audioclips([AudioFileClip(str(bg_audio_path))] * repeats)
        bg_looped = bg_looped.subclip(0, content.duration)
        bg_volume = cfg["bg_audio_volume"] * (10.0 ** (float(bg_audio_gain_db) / 20.0))
        logger.info("Background audio gain: %+.1f dB (volume %.3f -> %.3f)",
                    float(bg_audio_gain_db), cfg["bg_audio_volume"], bg_volume)
        bg_looped = bg_looped.volumex(bg_volume)
        bg_looped = bg_looped.audio_fadein(cfg["bg_audio_fadein_s"])
        bg_looped = bg_looped.audio_fadeout(cfg["bg_audio_fadeout_s"])
        mixed     = CompositeAudioClip([content.audio, bg_looped]) if content.audio else bg_looped
        content   = content.set_audio(mixed)
    else:
        logger.warning("Background audio not found for key '%s' -- skipping", bg_audio_name)

    # MoviePy write — to temp file if speed or branding will follow
    apply_speed    = abs(speed_factor - 1.0) > 1e-4
    apply_branding = bool(branding_file) and branding_mode and branding_mode != "none"
    needs_postpass = apply_speed or apply_branding

    moviepy_target = (
        project_path / ("final_" + project_name + "_raw.mp4")
        if needs_postpass else out_path
    )

    logger.info("Writing %s (%.1fs) ...", moviepy_target.name, content.duration)
    content.write_videofile(
        str(moviepy_target), fps=cfg["fps"], codec="libx264", audio_codec="aac",
        temp_audiofile=str(project_path / "final_tmp.m4a"),
        remove_temp=True, logger=None,
    )

    content.close()
    concat_tmp.unlink(missing_ok=True)

    # Optional speed pass
    if apply_speed:
        logger.info("Applying speed factor %.4f via FFmpeg ...", speed_factor)
        speed_out = project_path / ("final_" + project_name + "_spd.mp4")
        _ffmpeg_speed(moviepy_target, speed_out, speed_factor)
        moviepy_target.unlink(missing_ok=True)
        moviepy_target = speed_out
        logger.info("Speed pass complete -> %s", moviepy_target.name)

    # Optional branding concat
    if apply_branding:
        branding_path = cfg["branding_dir"] / branding_file
        if branding_path.exists():
            logger.info("Attaching branding (%s) as %s ...", branding_file, branding_mode)
            branded_out = project_path / ("final_" + project_name + "_branded.mp4")
            _ffmpeg_branding_concat(branding_path, moviepy_target, branded_out, branding_mode)
            moviepy_target.unlink(missing_ok=True)
            moviepy_target = branded_out
            logger.info("Branding pass complete -> %s", moviepy_target.name)
        else:
            logger.warning("Branding file not found: %s -- skipping", branding_path)

    # Move to final path if not already there
    if moviepy_target != out_path:
        if out_path.exists():
            out_path.unlink()
        moviepy_target.rename(out_path)

    # Auto-thumbnail: record where in the FINAL video the first "clean" pause sits
    # (a silent pause freezes the previous scene's image WITHOUT a subtitle — an
    # ideal cover frame). Stored as video_info.thumb_offset_ms so the Instagram
    # upload can default its cover frame to it. Computed here because only the
    # assembler knows the true clip durations plus the branding/speed offsets.
    intro_dur_s = 0.0
    if apply_branding and branding_mode in ("intro", "both"):
        bp = cfg["branding_dir"] / branding_file
        if bp.exists():
            intro_dur_s = _probe_duration(bp)
    try:
        thumb_ms = _compute_thumb_offset_ms(manifest, videos_dir, intro_dur_s, speed_factor)
        if thumb_ms is not None:
            manifest.setdefault("video_info", {})["thumb_offset_ms"] = thumb_ms
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            logger.info("Thumbnail offset (first clean pause): %d ms", thumb_ms)
    except Exception as e:
        logger.warning("Could not compute thumbnail offset: %s", e)

    logger.info("Done: %s", out_path)


def _compute_thumb_offset_ms(manifest, videos_dir, intro_dur_s, speed_factor):
    """Return the millisecond offset of the first clean cover frame in the FINAL
    video, or None if there is no suitable pause.

    Walks the scenes in the exact order they are concatenated (only those with a
    rendered clip), summing real clip durations. The target is the midpoint of the
    first silent pause (audio == null, description == "pause") that follows an
    image-bearing scene — during that pause the scene image is on screen with no
    subtitle. The pre-speed content offset is divided by the speed factor and the
    (un-sped) intro branding duration is added, matching how the final file is built:
    [intro] + speed(content).
    """
    speed = float(speed_factor) or 1.0
    running = 0.0          # cumulative pre-speed seconds of content
    prev_had_image = False
    for scene in manifest.get("scenes", []):
        clip = videos_dir / (scene["id"] + ".mp4")
        if not clip.exists():
            continue
        dur = _probe_duration(clip)
        is_pause = scene.get("audio") is None and scene.get("description") == "pause"
        if is_pause and prev_had_image and dur > 0:
            content_offset = running + dur / 2.0
            final_offset_s = intro_dur_s + content_offset / speed
            return int(round(final_offset_s * 1000))
        running += dur
        prev_had_image = bool((scene.get("image") or {}).get("file_path"))
    return None


def _probe_video_dims(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        capture_output=True, text=True).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


def _probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def _probe_video_frames(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout.strip()
    try:
        return int(out)
    except ValueError:
        return 0


def clamp_to_video_stream(clip, path, fps):
    """
    Trim `clip` so MoviePy never reads past the last real video frame.

    The AAC track of an MP4 is padded to a whole 1024-sample frame, so the
    container duration can exceed the video stream by a fraction of a frame.
    MoviePy trusts the container duration, computes one frame more than the
    stream holds, and the read of that phantom frame returns 0 bytes ("Using
    the last valid frame instead"); the audio reader fills the same gap by
    repeating the last decoded buffer -- the audible echo of the final moments.
    Clamping to nb_frames/fps removes the phantom tail entirely.
    """
    nframes = _probe_video_frames(path)
    if nframes:
        true_end = nframes / float(fps)
        if clip.duration and clip.duration > true_end:
            clip = clip.subclip(0, true_end)
    return clip


def _has_audio_stream(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout.strip()
    return bool(out)


def ffmpeg_concat_scenes(clip_paths, out_path, fps, target_w=None, target_h=None, sr=44100):
    """
    Gapless concatenation of per-scene clips via the FFmpeg concat *filter*.

    Why this exists: each per-scene .mp4 is AAC-encoded, which adds ~1024 priming
    samples and leaves the audio track slightly SHORTER than the video track. When
    MoviePy's concatenate_videoclips re-reads those files, it trusts the (longer)
    container duration and, at every clip boundary, fills the missing audio tail by
    REPEATING the last decoded buffer -- an audible fragment of the previous clip's
    sound bleeding into the following (often silent) pause clip.

    Decoding each input through the concat filter trims the priming and pads short
    audio segments with real silence, so the join is gapless and glitch-free. Every
    input is normalised (scaled+padded to a common canvas, fps, 44.1 kHz stereo) so
    mixed resolutions / framerates (e.g. raw inserted video clips) concat cleanly.

    ---------------------------------------------------------------------------
    COMMAND-LINE LENGTH WARNING (the cause of the [WinError 206] crash)
    ---------------------------------------------------------------------------
    This function builds ONE giant FFmpeg filtergraph -- roughly ~250 characters
    of text PER scene (see the `filt` string built below). A long dialog can
    produce 100-300+ scenes, so that single string can balloon to tens of
    thousands of characters.

    Windows caps a process's ENTIRE command line at 32,767 characters. When the
    filtergraph is passed inline (e.g. `-filter_complex "<huge string>"`), the
    command line blows past that cap and Python's subprocess call fails *before
    FFmpeg even starts* with:  OSError [WinError 206] "The filename or extension
    is too long". (Despite the wording, nothing is wrong with any filename -- it
    is the command line as a whole that is too long.)

    THE FIX, applied below: never put the filtergraph on the command line. Write
    it to a temporary text file and hand FFmpeg the file path via
    `-filter_complex_script`. The command line then only carries short tokens
    (the `-i <path>` inputs and a handful of flags), which stays comfortably
    under the limit even for hundreds of scenes.
    """
    clip_paths = [Path(p) for p in clip_paths]
    dims = [_probe_video_dims(p) for p in clip_paths]
    W = target_w or max(d[0] for d in dims)
    H = target_h or max(d[1] for d in dims)
    W -= W % 2
    H -= H % 2
    has_aud = [_has_audio_stream(p) for p in clip_paths]

    inputs, extra = [], []
    for p in clip_paths:
        inputs += ["-i", str(p)]
    # A clip with no audio track gets its own bounded silent source so the concat
    # filter has an [a] input for every segment.
    null_for = {}
    for i, p in enumerate(clip_paths):
        if not has_aud[i]:
            null_for[i] = len(clip_paths) + len(null_for)
            dur = max(_probe_duration(p), 0.05)
            extra += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", f"anullsrc=r={sr}:cl=stereo"]

    parts, labels = [], ""
    for i in range(len(clip_paths)):
        parts.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]"
        )
        a_src = i if has_aud[i] else null_for[i]
        parts.append(
            f"[{a_src}:a]aresample={sr}:async=1:first_pts=0,"
            f"aformat=sample_rates={sr}:channel_layouts=stereo[a{i}]"
        )
        labels += f"[v{i}][a{i}]"
    # ⚠️ THIS is the string that grows without bound. Each scene above appended
    # ~250 chars (two `parts` entries + a `labels` entry); `filt` is their join.
    # For a 150-scene dialog this is ~35,000 chars -- already over the Windows
    # command-line cap on its own. So it must NOT be passed inline as an argv
    # token; we route it through a file instead (see below).
    filt = ";".join(parts) + ";" + labels + f"concat=n={len(clip_paths)}:v=1:a=1[v][a]"

    # ---- Keep the huge filtergraph OFF the command line --------------------
    # Write `filt` to a temp .txt file and pass only its (short) PATH to FFmpeg
    # via `-filter_complex_script`. This is THE line that prevents the
    # [WinError 206] "command line too long" failure: argv now holds just the
    # `-i <path>` inputs plus a few flags, never the multi-KB graph itself.
    #
    # If you ever add another FFmpeg call whose arguments scale with the number
    # of scenes (filters, a long list of `-map`s, etc.), apply the same pattern:
    # move the big argument into a file rather than passing it inline.
    #
    # delete=False is required on Windows: a NamedTemporaryFile stays open and
    # cannot be opened a second time (by FFmpeg) while open, so we close it
    # ourselves, let FFmpeg read it, then remove it manually in `finally`.
    script = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    )
    try:
        script.write(filt)
        script.close()  # flush + release the handle so FFmpeg can open the file
        cmd = (
            ["ffmpeg", "-y"] + inputs + extra
            + ["-filter_complex_script", script.name, "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-r", str(fps),
               "-c:a", "aac", "-b:a", "192k", str(out_path)]
        )
        result = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        os.unlink(script.name)  # always clean up the temp filtergraph file
    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg scene concat failed (exit " + str(result.returncode) + "):\n"
            + result.stderr[-1500:]
        )
    return out_path


def _ffmpeg_branding_concat(branding_path, content_path, out_path, mode):
    """
    Prepend and/or append a branding clip around the main content.

    mode: "intro"  -> branding + content
          "outro"  -> content + branding
          "both"   -> branding + content + branding
    """
    if mode == "intro":
        inputs = [str(branding_path), str(content_path)]
        n = 2
    elif mode == "outro":
        inputs = [str(content_path), str(branding_path)]
        n = 2
    elif mode == "both":
        inputs = [str(branding_path), str(content_path), str(branding_path)]
        n = 3
    else:
        raise ValueError("branding_mode must be intro, outro, or both")

    filter_inputs = "".join("[" + str(i) + ":v][" + str(i) + ":a]" for i in range(n))
    filter_str    = filter_inputs + "concat=n=" + str(n) + ":v=1:a=1[v][a]"

    cmd = (
        ["ffmpeg", "-y"]
        + [part for inp in inputs for part in ["-i", inp]]
        + [
            "-filter_complex", filter_str,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            str(out_path),
        ]
    )
    logger.debug("FFmpeg branding cmd: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg branding concat failed (exit " + str(result.returncode) + "):\n"
            + result.stderr[-1000:]
        )


def _ffmpeg_speed(in_path, out_path, speed_factor):
    """Re-encode with FFmpeg to change playback speed without pitch shift."""
    pts_multiplier = 1.0 / speed_factor
    atempo_chain   = _build_atempo_chain(speed_factor)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(in_path),
        "-vf", "setpts=" + str(round(pts_multiplier, 6)) + "*PTS",
        "-af", atempo_chain,
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg speed pass failed (exit " + str(result.returncode) + "):\n"
            + result.stderr[-1000:]
        )


def _build_atempo_chain(speed_factor):
    filters   = []
    remaining = float(speed_factor)
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    filters.append("atempo=" + str(round(remaining, 6)))
    return ",".join(filters)


def _resolve_bg_audio(key, assets_dir):
    try:
        index = load_background_audio_index(assets_dir)
        if key in index:
            rel = index[key].get("file_path", "")
            if rel:
                return assets_dir / rel
    except Exception as e:
        logger.debug("Could not load background audio index: %s", e)

    fallback = assets_dir / "background_audio" / (key + ".mp3")
    return fallback if fallback.exists() else None


def main():
    p = argparse.ArgumentParser(description="Assemble per-scene clips into a final video.")
    p.add_argument("project_name")
    p.add_argument("--bg-audio", default="office", dest="bg_audio_name")
    p.add_argument("--bg-audio-gain-db", type=float, default=0.0, dest="bg_audio_gain_db",
                   help="Adjust background audio volume in dB relative to config "
                        "(positive = louder, negative = quieter, 0 = unchanged)")
    p.add_argument("--speed-factor", type=float, default=None, dest="speed_factor",
                   help="Playback speed multiplier (0.95 = 5 percent slower)")
    p.add_argument("--branding-file", dest="branding_file", default=None,
                   help="Branding video filename from assets/branding/ (e.g. intro.mp4)")
    p.add_argument("--branding-mode", dest="branding_mode", default="none",
                   choices=["none", "intro", "outro", "both"])
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args()
    assemble_video(
        a.project_name, a.bg_audio_name, a.overwrite, a.speed_factor,
        branding_file=a.branding_file, branding_mode=a.branding_mode,
        bg_audio_gain_db=a.bg_audio_gain_db,
    )


if __name__ == "__main__":
    main()
