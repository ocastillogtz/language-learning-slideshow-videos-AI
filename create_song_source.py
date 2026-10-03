"""
create_song_source.py
======================
Alternate front-end (like create_reading_source.py / create_promotional.py) that
builds the universal scene manifest for a "song" project from a FINISHED audio file
— e.g. a rap song about a grammar topic. No GPT dialog is generated.

Flow (build_song_project):
  1. Copy the provided song into project/audio/ and record it as project_metadata.master_audio.
  2. Transcribe it with ElevenLabs Scribe (speech-to-text) → words with timestamps.
     The raw response is cached to project/stt.json so re-runs cost nothing.
  3. Group words into line-by-line lyric subtitles (by pauses / punctuation / length).
  4. Chunk the timeline into image slots of `song_image_interval_seconds`, snapping each
     boundary to a lyric-line boundary so no line is split across two images.
  5. GPT art-directs one English `scene_visual` per slot from that slot's lyrics — the
     single character (default Amir) "sings" it in a consistent rapper costume.
  6. Emit one scene per slot: `_is_song_slice` marker, its duration, the per-slot lyric
     subtitle_segments (timed RELATIVE to the slot start), and a single-speaker image prompt.

The song itself is the only audio: create_audio skips these scenes (audio == null) and
assemble_video lays the master song over the finished video. No narration, no background
music, no branding.

CLI:  python create_song_source.py <project_name> --audio path/to/song.mp3
"""

import io
import os
import json
import shutil
import logging
import argparse
from pathlib import Path

from dotenv import load_dotenv
from pydub import AudioSegment
from elevenlabs.client import ElevenLabs
from openai import OpenAI

from utils_config import load_config, load_new_characters, target_language
from create_script import _action_single_prompt, _relax_clothing

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
load_dotenv()

_openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Default character + costume brief when the project doesn't set its own. The wardrobe
# is repeated into every scene_visual because the illustrator only honours a costume that
# is named in the scene text (see override_wardrobe in project_types.json).
DEFAULT_SONG_CHARACTER = "Amir"
DEFAULT_VISUAL_GUIDELINES = (
    "The character performs as a hip-hop rapper. He wears baggy streetwear — an "
    "oversized hoodie, a snapback cap worn backwards, gold chains and sunglasses — which "
    "REPLACES his usual clothes for this whole video. Urban music-video settings: a moody "
    "recording studio, a neon-lit stage, or a graffiti street backdrop. Energetic performing "
    "poses, holding a microphone, mid-verse."
)

_SENTENCE_ENDINGS = (".", "!", "?", "…")


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    """Atomically write manifest using a temp file + rename to prevent corruption."""
    tmp = manifest_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    tmp.replace(manifest_path)


# ── Speech-to-text ───────────────────────────────────────────────────────────

def _transcribe(mp3_path: Path, cache_path: Path, cfg: dict, overwrite: bool = False) -> dict:
    """Transcribe the song with ElevenLabs Scribe and return the response as a plain dict.

    Caches the raw response to `cache_path` (stt.json). A cached transcription is reused
    unless overwrite=True, so re-running the build costs no STT credits.
    """
    if cache_path.exists() and not overwrite:
        logger.info("Reusing cached transcription: %s", cache_path.name)
        return json.loads(cache_path.read_text(encoding="utf-8"))

    eleven = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
    logger.info("Transcribing %s with %s (%s) …", mp3_path.name,
                cfg["song_stt_model"], cfg["song_stt_language"])
    with open(mp3_path, "rb") as fh:
        audio_bytes = fh.read()
    result = eleven.speech_to_text.convert(
        file=io.BytesIO(audio_bytes),
        model_id=cfg["song_stt_model"],
        language_code=cfg["song_stt_language"],
        timestamps_granularity="word",
        tag_audio_events=False,
    )
    # Response is a pydantic model (SpeechToTextChunkResponseModel); normalise to a dict.
    data = result.model_dump() if hasattr(result, "model_dump") else dict(result)
    cache_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Transcription cached → %s", cache_path.name)
    return data


# ── Lyric lines ──────────────────────────────────────────────────────────────

def _words_to_lines(stt: dict, cfg: dict) -> list[dict]:
    """Group timestamped words into line-by-line lyric subtitles.

    A new line starts when the silent gap before a word exceeds song_line_gap_seconds,
    when the previous word ended a sentence, or when the current line would exceed
    song_max_line_chars. Returns [{text, start_ms, end_ms}] in order.
    """
    gap_s     = cfg["song_line_gap_s"]
    max_chars = cfg["song_max_line_chars"]

    words = [
        w for w in (stt.get("words") or [])
        if (w.get("type") == "word") and (w.get("text") or "").strip()
        and w.get("start") is not None and w.get("end") is not None
    ]

    lines: list[dict] = []
    cur_words: list[str] = []
    cur_start = None
    cur_end = None
    prev_end = None
    prev_text = ""

    def _flush():
        nonlocal cur_words, cur_start, cur_end
        if cur_words:
            lines.append({
                "text": " ".join(cur_words).strip(),
                "start_ms": int(round(cur_start * 1000)),
                "end_ms": int(round(cur_end * 1000)),
            })
        cur_words = []
        cur_start = None
        cur_end = None

    for w in words:
        text = w["text"].strip()
        start = float(w["start"])
        end = float(w["end"])

        big_gap = prev_end is not None and (start - prev_end) > gap_s
        sentence_break = prev_text.endswith(_SENTENCE_ENDINGS)
        too_long = cur_words and (len(" ".join(cur_words)) + 1 + len(text)) > max_chars

        if cur_words and (big_gap or sentence_break or too_long):
            _flush()

        if not cur_words:
            cur_start = start
        cur_words.append(text)
        cur_end = end
        prev_end = end
        prev_text = text

    _flush()
    return lines


# ── Timeline chunking ─────────────────────────────────────────────────────────

def _chunk_into_slots(lines: list[dict], total_ms: int, interval_ms: int) -> list[dict]:
    """Split the timeline into image slots of ~interval_ms each.

    A boundary is placed roughly every interval_ms so the illustration changes on that
    cadence even across instrumental (lyric-free) stretches. The only adjustment: a
    boundary that would land INSIDE a lyric line is pushed forward to that line's end, so
    a line is never split across two images. Each slot is {start_ms, end_ms, lines:[...]};
    the last slot always reaches total_ms so the video length equals the song length.
    """
    total_ms = max(total_ms, (lines[-1]["end_ms"] if lines else 0), 1)
    lines = sorted(lines, key=lambda l: l["start_ms"])

    # 1. Interior boundaries on a ~interval grid, nudged out of any lyric line.
    bounds: list[int] = []
    t = interval_ms
    while t < total_ms:
        inside = next((l for l in lines if l["start_ms"] < t < l["end_ms"]), None)
        b = inside["end_ms"] if inside else t
        if b >= total_ms:
            break
        if not bounds or b > bounds[-1]:
            bounds.append(b)
        t = b + interval_ms

    # 2. Slots between consecutive boundaries; assign each line by its start time.
    edges = [0] + bounds + [total_ms]
    slots: list[dict] = []
    for i in range(len(edges) - 1):
        start, end = edges[i], edges[i + 1]
        if end <= start:
            continue
        slot_lines = [l for l in lines if start <= l["start_ms"] < end]
        slots.append({"start_ms": start, "end_ms": end, "lines": slot_lines})
    return slots


# ── GPT art-direction ─────────────────────────────────────────────────────────

def _art_direct(slot_texts: list[str], character: str, visual_guidelines: str,
                level: str, model: str) -> list[str]:
    """One GPT call: return an English scene_visual for each slot from its lyrics.

    Each scene_visual keeps `character` in the consistent costume, setting, mood and
    composition described by visual_guidelines and shows them performing/acting out the
    meaning of that slot's lyrics. The costume, genre and any composition treatment
    (e.g. a memory/flashback double-exposure overlay) come entirely from visual_guidelines,
    so this prompt makes no assumption about the musical style.
    Returns a list of scene_visual strings, one per slot (padded if the model returns fewer).
    """
    numbered = "\n".join(
        f"{i + 1}. {txt.strip() or '(instrumental — no lyrics in this slot)'}"
        for i, txt in enumerate(slot_texts)
    )
    prompt = (
        f"You are art-directing a {target_language()} language-learning MUSIC VIDEO (level {level}). "
        f"One performer, {character}, performs the whole song. The video shows a new "
        f"illustration for each numbered slot below; each slot lists the lyrics sung during it.\n\n"
        f"ART DIRECTION — costume, instrument, setting, mood and COMPOSITION (keep CONSISTENT "
        f"across every slot and follow it exactly):\n{visual_guidelines}\n\n"
        f"For EACH numbered slot, write ONE vivid English 'scene_visual' (2-4 sentences) that "
        f"obeys the art direction above. Rules for every scene_visual:\n"
        f"- {character} is the only real person; describe the performing pose, expression and "
        f"gesture, and RESTATE the costume and instrument named in the art direction (the "
        f"illustrator only draws what is explicitly named).\n"
        f"- Illustrate the MEANING of that slot's lyrics: stage a concrete action, object, place "
        f"or memory that reflects what is being sung, so the image reinforces the words. If the "
        f"art direction calls for a memory / flashback / double-exposure overlay, put that lyric "
        f"meaning in the overlaid dream layer and describe how it softly blends with {character}.\n"
        f"- Vary the pose / camera / backdrop and the overlaid memory between slots so "
        f"consecutive images look clearly different.\n"
        f"- If a slot's lyrics are only spelled-out letters or the bare list of prepositions "
        f"(durch, ohne, bis, gegen, für, um), do NOT draw letters — instead illustrate the "
        f"song's overarching story/theme for that moment.\n"
        f"- For an instrumental slot with no lyrics, show an evocative performing moment in the "
        f"same costume, mood and composition.\n"
        f"- NO readable text, letters, logos or written words on anything.\n\n"
        f"SLOTS:\n{numbered}\n\n"
        f'Output ONLY JSON: {{"scene_visuals": ["<slot 1>", "<slot 2>", ...]}} with exactly '
        f"{len(slot_texts)} strings in slot order. No markdown, no backticks."
    )
    logger.info("Art-directing %d slots with %s …", len(slot_texts), model)
    resp = _openai.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    raw = resp.choices[0].message.content
    parsed = json.loads(raw)
    visuals = parsed.get("scene_visuals") or parsed.get("scenes") or []
    # Tolerate a list of {scene_visual: ...} objects as well as a flat list of strings.
    out: list[str] = []
    for v in visuals:
        if isinstance(v, dict):
            out.append((v.get("scene_visual") or "").strip())
        else:
            out.append(str(v).strip())
    # Pad / trim so there is exactly one visual per slot.
    while len(out) < len(slot_texts):
        out.append(f"{character} performing energetically, mid-verse.")
    return out[:len(slot_texts)]


# ── Build ──────────────────────────────────────────────────────────────────────

def build_song_project(
    project_name: str,
    audio_path: str,
    character: str | None = None,
    visual_guidelines: str | None = None,
    overwrite_stt: bool = False,
) -> None:
    """Build the scene manifest for a song project from a finished audio file."""
    cfg           = load_config()
    project_path  = cfg["projects_dir"] / project_name
    manifest_path = project_path / "project_manifest.json"
    audio_dir     = project_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No manifest for '{project_name}'. Create it first: "
            f"create_project.py {project_name} --type song --context \"<topic>\""
        )
    src = Path(audio_path)
    if not src.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    gen   = manifest.setdefault("generation_config", {})
    character = character or (gen.get("characters") or [None])[0] or DEFAULT_SONG_CHARACTER
    visual_guidelines = (
        visual_guidelines
        or (gen.get("visual_guidelines") or "").strip()
        or DEFAULT_VISUAL_GUIDELINES
    )
    gen["characters"] = [character]
    gen["visual_guidelines"] = visual_guidelines

    chars_data = load_new_characters(cfg["assets_dir"])
    if character not in chars_data:
        raise ValueError(f"Unknown character '{character}'. Available: {sorted(chars_data)}")
    char_data = chars_data[character]

    # 1. Copy the song into the project and record it as the master audio track.
    dest = audio_dir / "song.mp3"
    shutil.copyfile(src, dest)
    master_rel = "audio/song.mp3"
    manifest.setdefault("project_metadata", {})["master_audio"] = master_rel
    logger.info("Master audio: %s", master_rel)

    # 2. Transcribe (cached).
    stt = _transcribe(dest, project_path / "stt.json", cfg, overwrite=overwrite_stt)

    # 3. Lyric lines.
    lines = _words_to_lines(stt, cfg)
    logger.info("Grouped %d words into %d lyric lines",
                len([w for w in stt.get("words", []) if w.get("type") == "word"]), len(lines))

    # Total duration: prefer the STT-reported length, fall back to reading the file.
    total_ms = int(round(float(stt.get("audio_duration_secs") or 0) * 1000))
    if total_ms <= 0:
        total_ms = len(AudioSegment.from_file(dest))

    # 4. Chunk into image slots.
    interval_ms = cfg["song_image_interval_ms"]
    slots = _chunk_into_slots(lines, total_ms, interval_ms)
    logger.info("Chunked into %d image slots of ~%.1fs", len(slots), interval_ms / 1000.0)

    # 5. Art-direct one scene_visual per slot.
    slot_texts = [" ".join(l["text"] for l in s["lines"]) for s in slots]
    scene_visuals = _art_direct(slot_texts, character, visual_guidelines,
                                gen.get("level", cfg["level"]), cfg["script_model"])

    # 6. Emit one scene per slot.
    framing_tokens = None  # falls back to config framing tokens
    scenes: list[dict] = []
    for idx, (slot, scene_visual) in enumerate(zip(slots, scene_visuals), start=1):
        sid = f"scene_{idx:03d}"
        slot_start = slot["start_ms"]
        dur_ms = max(1, slot["end_ms"] - slot_start)
        # Lyric subtitle segments, timed RELATIVE to the slot start and clamped to the slot.
        segments = []
        for l in slot["lines"]:
            seg_start = max(0, l["start_ms"] - slot_start)
            seg_end = min(dur_ms, l["end_ms"] - slot_start)
            if seg_end > seg_start and l["text"]:
                segments.append({"text": l["text"], "start_ms": seg_start, "end_ms": seg_end})
        subtitle_text = " ".join(l["text"] for l in slot["lines"]).strip()

        # song is a wardrobe-override type: relax the "match reference clothing" line so the
        # rapper costume named in the scene_visual (not Amir's default shirt) wins at render.
        prompt = _relax_clothing(
            _action_single_prompt(character, char_data, visual_guidelines,
                                  scene_visual, framing_tokens)
        )
        scenes.append({
            "id": sid,
            "description": f"song slice {idx}",
            "characters": [character],
            "_is_song_slice": True,
            "image": {
                "file_path": None,
                "prompt_to_create": prompt,
                "reference_type": "single_speaker",
                "scene_visual": scene_visual,
            },
            "audio": None,
            "subtitle_text": subtitle_text or None,
            "subtitle_segments": segments,
            "duration_ms": dur_ms,
        })

    manifest["scenes"] = scenes

    # Minimal video_info so downstream steps (and uploads) have something to work with.
    vinfo = manifest.setdefault("video_info", {})
    vinfo.setdefault("video_format", "vertical")
    if not vinfo.get("title"):
        vinfo["title"] = project_name.replace("_", " ").title()

    _write_manifest(manifest_path, manifest)
    logger.info("Song source built: %d scenes, %.1fs total → %s",
                len(scenes), total_ms / 1000.0, manifest_path)


def main() -> None:
    p = argparse.ArgumentParser(description="Build a song project's scenes from an audio file")
    p.add_argument("project_name")
    p.add_argument("--audio", required=True, help="Path to the finished song audio file")
    p.add_argument("--character", default=None,
                   help=f"Performing character (default: project's, else {DEFAULT_SONG_CHARACTER})")
    p.add_argument("--visual-guidelines", default=None, dest="visual_guidelines",
                   help="Costume/setting brief kept consistent across every slot")
    p.add_argument("--overwrite-stt", action="store_true",
                   help="Re-transcribe even if stt.json is cached")
    a = p.parse_args()
    build_song_project(a.project_name, a.audio, a.character, a.visual_guidelines,
                       a.overwrite_stt)


if __name__ == "__main__":
    main()
