"""
assemble_reading.py
===================
Phase 5 of reading_together: package the rendered per-scene clips into

  final_<project>_part1.mp4 ... partN.mp4   (vertical 6-sentence shorts)
  final_<project>_long.mp4                  (one horizontal video, all sentences)

Vertical part clips are read from   projects/<p>/videos/<scene>.mp4
Horizontal long clips are read from projects/<p>/videos/h/<scene>.mp4
(produced by a horizontal create_videos pass: format_override="horizontal",
out_subdir="h"). If the horizontal clips are missing, the long video falls back
to the vertical clips so something is still produced.

Reuses the background-audio / speed / branding helpers from assemble_video.
"""

import json
import logging
import argparse
from pathlib import Path

import numpy as np
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeAudioClip,
    ImageClip, TextClip, ColorClip, CompositeVideoClip,
    concatenate_videoclips, concatenate_audioclips,
)
from moviepy.config import change_settings

import assemble_video as av
from utils_config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# OVERLAY HELPERS (vertical part shorts only)
# =============================================================================

def _silent_audio(duration, fps=44100):
    """A silent stereo audio track of the given duration (for freeze-frame tails)."""
    from moviepy.audio.AudioClip import AudioArrayClip
    n = max(1, int(duration * fps))
    return AudioArrayClip(np.zeros((n, 2), dtype=np.float32), fps=fps).set_duration(duration)


def _corner_label_layers(text, duration, cfg, canvas_w=None):
    """
    Build a small upper-RIGHT corner label (with a soft dark backing box) shown for
    the whole part. `text` is e.g. "Teil 1". It is right-aligned using the same right
    margin as the subtitles (sub_margin_right) so it doesn't collide with the reading
    book icon in the upper-left corner. Returns a list of layers.
    """
    label = TextClip(
        text, font=cfg["nar_font"], fontsize=cfg["part_label_fontsize"],
        color=cfg["part_label_color"], stroke_color=cfg["part_label_stroke_color"],
        stroke_width=cfg["part_label_stroke_width"], method="label",
    ).set_duration(duration)
    px, py = cfg["part_label_bg_padding_x"], cfg["part_label_bg_padding_y"]
    my     = cfg["part_label_margin_y"]
    # Align the label's right edge to the subtitle right margin (W - sub_margin_right),
    # so the part marker hugs the right side with the same inset as the subtitles.
    W      = canvas_w or cfg["target_w"]
    mx     = W - cfg["sub_margin_right"] - label.w
    bg = (ColorClip(size=(label.w + px * 2, label.h + py * 2), color=(0, 0, 0))
          .set_duration(duration)
          .set_opacity(cfg["part_label_bg_opacity"]))
    return [bg.set_position((mx - px, my - py)), label.set_position((mx, my))]


def _continuation_tail(content, cfg):
    """
    Freeze the last frame of `content` for cfg["continuation_seconds"] and overlay
    the centered continuation legend (e.g. "Fortsetzung folgt..."). Silent audio.
    """
    secs = float(cfg["continuation_seconds"])
    fps  = cfg["fps"]
    t    = max(0.0, content.duration - max(1.0 / fps, 0.05))
    base = ImageClip(content.get_frame(t)).set_duration(secs)
    w, h = base.w, base.h
    legend = TextClip(
        cfg["continuation_text"], font=cfg["nar_font"],
        fontsize=cfg["continuation_fontsize"], color=cfg["continuation_color"],
        stroke_color=cfg["continuation_stroke_color"],
        stroke_width=cfg["continuation_stroke_width"],
        method="caption", size=(int(w * 0.85), None), align="center",
    ).set_duration(secs).set_position(("center", "center"))
    tail = CompositeVideoClip([base, legend], size=(w, h)).set_duration(secs)
    return tail.set_audio(_silent_audio(secs))


def _branding_concat_fit(branding_path, content_path, out_path, mode, W, H, fps):
    """
    Prepend/append a branding clip around the content, scaling+padding every input
    to W x H (with normalized fps / SAR / audio). Unlike the plain concat in
    assemble_video, this lets a single branding file be reused for both the
    vertical parts (1080x1920) and the horizontal long video (1920x1080) without
    requiring the branding clip to match each target resolution.
    """
    import subprocess
    if mode == "intro":
        inputs = [str(branding_path), str(content_path)]; n = 2
    elif mode == "outro":
        inputs = [str(content_path), str(branding_path)]; n = 2
    elif mode == "both":
        inputs = [str(branding_path), str(content_path), str(branding_path)]; n = 3
    else:
        raise ValueError("branding_mode must be intro, outro, or both")

    filters, concat_inputs = [], ""
    for i in range(n):
        filters.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]"
        )
        filters.append(
            f"[{i}:a]aresample=44100,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]"
        )
        concat_inputs += f"[v{i}][a{i}]"
    filter_str = ";".join(filters) + ";" + concat_inputs + f"concat=n={n}:v=1:a=1[v][a]"

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
    logger.debug("FFmpeg branding (fit) cmd: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "FFmpeg branding concat (fit) failed (exit "
            + str(result.returncode) + "):\n" + result.stderr[-1200:]
        )


def group_scenes_into_parts(scenes, per_part=None):
    """
    Map part index -> ordered list of scene ids.

    If per_part is given, parts are computed live by counting reading scenes in
    order (every `per_part` reading sentences start a new part) -- this is the
    authoritative grouping set at assembly time. If per_part is None, the baked
    scene["_part_index"] is used as a fallback.

    A short final remainder is FUSED into the previous part instead of becoming a
    tiny standalone part. E.g. with per_part=7 and 10 sentences you get a single
    part of 10 (7 + 3); with 17 sentences you get parts of 7 and 10 (7 + 7+3).

    Pause / non-reading scenes inherit the part of the most recent reading scene
    (so a trailing pause stays with its part).
    """
    parts = {}
    current = 0
    if per_part:
        per_part = max(1, int(per_part))
        total_reading = sum(1 for s in scenes if s.get("_reading"))
        full = total_reading // per_part
        cap = max(0, full - 1)   # fold any remainder into the last full part
        reading_seen = 0
        for s in scenes:
            if s.get("_reading"):
                current = min(reading_seen // per_part, cap)
                reading_seen += 1
            parts.setdefault(current, []).append(s["id"])
        return parts
    for s in scenes:
        if s.get("_reading"):
            current = s.get("_part_index", current)
        parts.setdefault(current, []).append(s["id"])
    return parts


def _finalize(clip_paths, out_path, cfg, assets_dir, project_path,
              bg_audio_name, speed_factor, branding_file, branding_mode,
              overwrite, tag, corner_label=None, add_continuation=False,
              bg_audio_gain_db=0.0):
    """
    Concat clips -> [continuation end-card] -> [corner label] -> bg audio ->
    speed -> branding -> out_path. Returns out_path or None.

    corner_label:     text shown top-left for the whole clip (e.g. "Teil 1"), or None.
    add_continuation: append a frozen end-card with the continuation legend.
    """
    if out_path.exists() and not overwrite:
        logger.info("exists: %s -- skip (use overwrite)", out_path.name)
        return out_path
    clip_paths = [p for p in clip_paths if p.exists()]
    if not clip_paths:
        logger.warning("no clips for %s -- skipped", out_path.name)
        return None

    # Gapless FFmpeg concat (trims AAC priming, pads short audio tails with real
    # silence) instead of MoviePy's concatenate_videoclips, which repeats the last
    # audio buffer at each boundary -> tiny audible echo before silent pauses.
    concat_tmp = project_path / ("_concat_" + tag + ".mp4")
    av.ffmpeg_concat_scenes(clip_paths, concat_tmp, fps=cfg["fps"])
    content = VideoFileClip(str(concat_tmp))

    # Append the continuation end-card (frozen last frame + centered legend).
    if add_continuation and float(cfg.get("continuation_seconds", 0)) > 0:
        tail    = _continuation_tail(content, cfg)
        content = concatenate_videoclips([content, tail], method="compose")

    # Overlay the part label (e.g. "Teil 1") top-left for the whole clip.
    if corner_label:
        base_audio = content.audio
        layers     = [content] + _corner_label_layers(corner_label, content.duration, cfg, content.w)
        content    = (CompositeVideoClip(layers, size=content.size)
                      .set_duration(content.duration)
                      .set_audio(base_audio))

    bg_audio_path = av._resolve_bg_audio(bg_audio_name, assets_dir)
    if bg_audio_path and bg_audio_path.exists():
        bg_clip   = AudioFileClip(str(bg_audio_path))
        repeats   = int(content.duration / bg_clip.duration) + 2
        bg_looped = concatenate_audioclips([AudioFileClip(str(bg_audio_path))] * repeats)
        bg_volume = cfg["bg_audio_volume"] * (10.0 ** (float(bg_audio_gain_db) / 20.0))
        bg_looped = bg_looped.subclip(0, content.duration).volumex(bg_volume)
        bg_looped = bg_looped.audio_fadein(cfg["bg_audio_fadein_s"]).audio_fadeout(cfg["bg_audio_fadeout_s"])
        mixed     = CompositeAudioClip([content.audio, bg_looped]) if content.audio else bg_looped
        content   = content.set_audio(mixed)

    apply_speed    = abs((speed_factor or 1.0) - 1.0) > 1e-4
    apply_branding = bool(branding_file) and branding_mode and branding_mode != "none"
    needs_post     = apply_speed or apply_branding
    target = (project_path / (out_path.stem + "_raw.mp4")) if needs_post else out_path

    final_w, final_h = content.size   # capture before close (parts 1080x1920, long 1920x1080)

    logger.info("Writing %s (%.1fs, %d clips) ...", target.name, content.duration, len(clip_paths))
    content.write_videofile(
        str(target), fps=cfg["fps"], codec="libx264", audio_codec="aac",
        temp_audiofile=str(project_path / (tag + "_tmp.m4a")), remove_temp=True, logger=None,
    )
    content.close()
    concat_tmp.unlink(missing_ok=True)

    if apply_speed:
        spd = project_path / (out_path.stem + "_spd.mp4")
        av._ffmpeg_speed(target, spd, speed_factor)
        target.unlink(missing_ok=True)
        target = spd

    if apply_branding:
        branding_path = cfg["branding_dir"] / branding_file
        if branding_path.exists():
            branded = project_path / (out_path.stem + "_branded.mp4")
            # Scale+pad the branding clip to this output's resolution so a single
            # intro file works for both vertical parts and the horizontal long video.
            _branding_concat_fit(branding_path, target, branded, branding_mode,
                                 final_w, final_h, cfg["fps"])
            target.unlink(missing_ok=True)
            target = branded
        else:
            logger.warning("branding file not found: %s -- skipping", branding_path)

    if target != out_path:
        if out_path.exists():
            out_path.unlink()
        target.rename(out_path)
    logger.info("Done: %s", out_path.name)
    return out_path


def assemble_reading(project_name, bg_audio_name="office", overwrite=False,
                     speed_factor=None, branding_file=None, branding_mode="none",
                     make_parts=True, make_long=True, per_part=None,
                     bg_audio_gain_db=0.0):
    cfg = load_config()
    assets_dir = cfg["assets_dir"]
    project_path = cfg["projects_dir"] / project_name
    if speed_factor is None:
        speed_factor = cfg.get("speed_factor", 1.0)
    speed_factor = float(speed_factor)
    if cfg.get("imagemagick"):
        change_settings({"IMAGEMAGICK_BINARY": cfg["imagemagick"]})

    with open(project_path / "project_manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    scenes = manifest.get("scenes", [])

    # sentences-per-part: explicit arg wins, else the value stored at build time, else 6
    if per_part in (None, ""):
        per_part = (manifest.get("generation_config", {})
                            .get("reading", {})
                            .get("sentences_per_part", 6))
    per_part = max(1, int(per_part))

    videos_dir = project_path / "videos"
    h_dir = videos_dir / "h"
    outputs = []

    # --- vertical parts ---
    if make_parts:
        parts     = group_scenes_into_parts(scenes, per_part=per_part)
        part_keys = sorted(parts)
        last_key  = part_keys[-1] if part_keys else None
        word      = cfg.get("part_label_word", "Teil")
        for p in part_keys:
            clip_paths = [videos_dir / f"{sid}.mp4" for sid in parts[p]]
            out = project_path / f"final_{project_name}_part{p + 1}.mp4"
            res = _finalize(clip_paths, out, cfg, assets_dir, project_path,
                            bg_audio_name, speed_factor, branding_file, branding_mode,
                            overwrite, tag=f"part{p + 1}",
                            corner_label=f"{word} {p + 1}",
                            add_continuation=(p != last_key),
                            bg_audio_gain_db=bg_audio_gain_db)
            if res:
                outputs.append(res)

    # --- horizontal long (all scenes) ---
    if make_long:
        src_dir = h_dir if h_dir.exists() else videos_dir
        if src_dir is videos_dir:
            logger.warning("No horizontal clips in %s -- long video will use the vertical clips. "
                           "Render a horizontal pass first for a true 16:9 long video.", h_dir)
        clip_paths = [src_dir / f"{s['id']}.mp4" for s in scenes]
        out = project_path / f"final_{project_name}_long.mp4"
        res = _finalize(clip_paths, out, cfg, assets_dir, project_path,
                        bg_audio_name, speed_factor, branding_file, branding_mode,
                        overwrite, tag="long", bg_audio_gain_db=bg_audio_gain_db)
        if res:
            outputs.append(res)

    logger.info("assemble_reading produced %d file(s).", len(outputs))
    return outputs


def main():
    p = argparse.ArgumentParser(description="Assemble reading_together parts + long video")
    p.add_argument("project_name")
    p.add_argument("--bg-audio", default="office", dest="bg_audio_name")
    p.add_argument("--bg-audio-gain-db", type=float, default=0.0, dest="bg_audio_gain_db",
                   help="Adjust background audio volume in dB relative to config "
                        "(positive = louder, negative = quieter, 0 = unchanged)")
    p.add_argument("--speed-factor", type=float, default=None, dest="speed_factor")
    p.add_argument("--branding-file", dest="branding_file", default=None)
    p.add_argument("--branding-mode", dest="branding_mode", default="none",
                   choices=["none", "intro", "outro", "both"])
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--no-parts", action="store_true")
    p.add_argument("--no-long", action="store_true")
    p.add_argument("--per-part", type=int, default=None, dest="per_part",
                   help="Sentences per vertical part (default: value from build, else 6)")
    a = p.parse_args()
    assemble_reading(a.project_name, a.bg_audio_name, a.overwrite, a.speed_factor,
                     branding_file=a.branding_file, branding_mode=a.branding_mode,
                     make_parts=not a.no_parts, make_long=not a.no_long, per_part=a.per_part,
                     bg_audio_gain_db=a.bg_audio_gain_db)


if __name__ == "__main__":
    main()
