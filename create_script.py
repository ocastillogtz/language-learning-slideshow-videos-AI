"""
create_script.py

Generate script and populate project_manifest.json.
Extracts: insights, context, visual_context (global), conversation.

Each dialogue line now carries a per-scene visual_context as the 5th
pipe-delimited field, describing what is visually happening in that moment
(not just the room, but the scene action / subject being discussed).

Non-dialogue lines (pause, sfx) use an empty 5th field so the format
stays uniformly parseable by position.

Conversation line format:
  dialogue:  char|mode|section|text|visual_context
  pause:     pause||subtitle|duration_ms|
  sfx:       sfx|||name|
"""

import os
import re
import json
import logging
import argparse
import configparser
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY not found")
client = OpenAI(api_key=api_key)


# =========================
# CONFIG LOADER
# =========================
def load_config(config_path="config.ini"):
    config = configparser.ConfigParser()
    config.read(config_path)
    projects_dir = Path(config["paths"]["projects_dir"])
    model        = config.get("script", "openai_model", fallback="gpt-4.1-nano")
    level        = config.get("script", "level", fallback="B2")
    log_level    = config.get("script", "log_level", fallback="INFO")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    return projects_dir, model, level


# =========================
# PROMPT BUILDER
# =========================
def build_prompt(level: str, scene: str, learning: str) -> str:
    return f"""
    task: dialogue
    lang: DE
    level: {level}

    format:
    <insights>
    </insights>
    <context>
    </context>
    <visual_context>
    </visual_context>
    <conversation>
    char|mode|section|text|visual_context
    </conversation>

    follow this conversation block scheme:
    introduction
    1. introduction: The narrator introduces the context
    dialog
    2. dialog element 1
    3. dialog element 2
    4. dialog element 3
    repeat section: The narrator guides
    5. repeat introduction: bitte wiederholen
    6. repeat element 1
    7. repeat element 2
    8. repeat element 3


    rules:
    - Write detailed learning insights based on the level {level}
    - Use german characters, we can have UTF-8.
    - The FIRST line of <conversation> MUST always be a Narrator line introducing the scene
    - All conversations must have the introduction, the dialog andthe repeating section.
    - The speaker that requests something or proposes something, uses a faster speech and the one that replies or inquires, uses a slower speech.
    - narrator introduces context at the start
    - short, natural sentences
    - include repetition section after dialog section
    - in the repetition section the narrator uses a slower speak mode
    - add sfx|||bell| before each repetition phrase
    - pauses: pause|||<ms>|  (no text) OR  pause||<subtitle_text>|<ms>|  (with subtitle)
    - sfx: sfx|||<n>|
    - output strictly in format, no markdown, no extra text

    <visual_context> rules (global — used for narrator/establishing shot):
    - Describe the physical scene in detail: location, time of day, lighting, atmosphere
    - For each character: exact position in frame, clothing (colors, style), posture
    - Describe furniture, objects, colors — anything that must stay consistent across images
    - Write in English, concise but specific (3-6 sentences)
    - Do not mention the topic of conversation here

    per-line visual_context rules (5th field on EVERY line, including pause and sfx):
    - For dialogue lines: describe what is VISUALLY HAPPENING in that specific moment
    - If the character is talking ABOUT something (going to the movies, seeing a cat,
      fixing a pipe) → show THAT THING. Example: the character standing at a cinema
      entrance, a street cat looking up at the character, hands under a leaking sink.
    - Very important to add the position of the characters in its context who is on the right and left of the image, very explicit.
    - For narrator introduction and repeat lines: show the characters in the room
      in the establishing shot composition described in <visual_context>
    - this visual context is going to help us build images, so if they happen in the same environment, the characters should NOT switch places
    - Be specific: character position, action, expression, environment. 1-2 sentences in English.
    - For pause lines: empty field — end the line with | like: pause|||1000|
    - For sfx lines: empty field — end the line with | like: sfx|||bell|

    example:

    <insights>
    In diesem Dialog werden einige fortgeschrittene Wörter verwendet:
    - "Bericht" (Report) - ein schriftliches Dokument.
    </insights>
    <context>
    Die Szene findet in einem deutschen Büro statt.
    </context>
    <visual_context>
    Bright modern office, large windows with natural daylight on the left. Zahra stands on the left wearing a dark navy blazer and white blouse, arms slightly crossed. Olena sits at a light oak desk on the right, wearing a light grey cardigan, leaning forward attentively. The desk has a laptop, a white coffee mug, and a small potted plant. Walls are white with a framed abstract print in muted blues.
    </visual_context>
    <conversation>
    Narrator|clear slow|introduction|In diesem Szenario ist Zahra die Chefin, die Olena einen Auftrag gibt.|Zahra stands confidently near the window, Olena looks up from her desk with an attentive expression, morning light fills the room.
    pause|||2000|
    Zahra|normal|dialog|Ich brauche einen Bericht bis Freitag.|Zahra leans toward Olena's desk, gesturing with one hand, direct eye contact, professional office setting.
    pause|||700|
    Olena|slower|dialog|Alles klar, ich fange sofort an.|Olena turns to her laptop and begins typing, focused expression, coffee mug beside her keyboard.
    pause|||700|
    Zahra|normal|dialog|Perfekt. Danke.|Zahra gives a brief approving nod and walks toward the door, Olena watches from her desk.
    sfx|||bell|
    Narrator|slower|repeat|Bitte wiederholen|Both characters in the room, Olena at desk, Zahra near window, calm atmosphere.
    pause|||800|
    sfx|||bell|
    Narrator|slower|repeat|Ich brauche einen Bericht bis Freitag.|
    pause||Ich brauche einen Bericht bis Freitag.|3500|
    sfx|||bell|
    Narrator|slower|repeat|Alles klar, ich fange sofort an.|
    pause||Alles klar, ich fange sofort an.|3500|
    sfx|||bell|
    Narrator|slower|repeat|Perfekt. Danke.|
    pause||Perfekt. Danke.|3500|
    </conversation>

    scene:
    {scene}

    learning points:
    {learning}
    """.strip()


# =========================
# TAG EXTRACTOR
# =========================
def extract_tag(content: str, tag: str) -> str:
    pattern = rf"<{tag}>(.*?)</{tag}>"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        logger.warning(f"Missing <{tag}>")
        return ""
    return match.group(1).strip()


# =========================
# PARSE CONVERSATION → SCENES
# =========================
def parse_conversation(conversation: str):
    scenes = []
    lines  = [l.strip() for l in conversation.split("\n") if l.strip()]

    recent_characters = []
    window_size = 3

    for idx, line in enumerate(lines, start=1):
        parts    = line.split("|")
        scene_id = f"scene_{idx:03d}"

        if len(parts) < 2:
            logger.warning(f"Skipping malformed line {idx}: {line!r}")
            continue

        char_raw = parts[0].strip()
        char     = char_raw.lower()

        # PAUSE  —  pause||subtitle|duration_ms|
        if char == "pause":
            subtitle = parts[2].strip() if len(parts) > 2 else ""
            try:
                duration = int(parts[3].strip()) if len(parts) > 3 and parts[3].strip() else 1000
            except (ValueError, IndexError):
                duration = 1000
            scenes.append({
                "id": scene_id, "type": "pause",
                "text": subtitle, "duration_ms": duration
            })
            continue

        # SFX  —  sfx|||name|
        if char == "sfx":
            scenes.append({
                "id": scene_id, "type": "sfx",
                "name": parts[3].strip() if len(parts) > 3 else parts[-1].strip()
            })
            continue

        # DIALOGUE  —  char|mode|section|text|visual_context
        if len(parts) < 4:
            logger.warning(f"Skipping incomplete dialogue line {idx}: {line!r}")
            continue

        speaker      = char_raw
        mode         = parts[1].strip()
        section      = parts[2].strip()
        text         = parts[3].strip()
        scene_visual = parts[4].strip() if len(parts) > 4 else ""

        if char != "narrator" and section == "dialog":
            if speaker not in recent_characters:
                recent_characters.append(speaker)
            if len(recent_characters) > window_size:
                recent_characters.pop(0)

        scene_characters = [c for c in recent_characters if c.lower() != "narrator"]
        is_narrator      = (char == "narrator")

        scenes.append({
            "id": scene_id, "type": "dialogue",
            "character": speaker, "mode": mode, "section": section, "text": text,
            "visual_context": scene_visual,
            "characters": scene_characters, "is_narrator": is_narrator,
            "audio": None, "image": None
        })

    return scenes


# =========================
# OPENAI CALL
# =========================
def generate_script(prompt: str, model: str) -> str:
    logger.info("Generating script from OpenAI...")
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )
    logger.debug(f"Raw response: {response}")
    return response.choices[0].message.content


# =========================
# MAIN
# =========================
def create_script(project_name: str):
    projects_dir, model, level = load_config()
    project_path  = projects_dir / project_name
    manifest_path = project_path / "project_manifest.json"

    if not manifest_path.exists():
        raise FileNotFoundError("project_manifest.json not found")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    scene    = manifest["inputs"]["scene"]
    learning = manifest["inputs"]["learning_points"]

    prompt     = build_prompt(level, scene, learning)
    raw_output = generate_script(prompt, model)

    insights       = extract_tag(raw_output, "insights")
    context        = extract_tag(raw_output, "context")
    visual_context = extract_tag(raw_output, "visual_context")
    conversation   = extract_tag(raw_output, "conversation")

    if not conversation:
        raise ValueError("Model returned empty <conversation> block")

    first_dialogue = next(
        (l for l in conversation.splitlines()
         if l.strip() and "|" in l and l.split("|")[0].strip().lower() not in ("pause", "sfx")),
        None
    )
    if first_dialogue and not first_dialogue.lower().startswith("narrator"):
        logger.warning("First dialogue line is not Narrator — consider re-generating")

    (project_path / "insight.txt").write_text(insights, encoding="utf-8")
    (project_path / "context.txt").write_text(context, encoding="utf-8")
    (project_path / "visual_context.txt").write_text(visual_context, encoding="utf-8")
    (project_path / "script.txt").write_text(conversation, encoding="utf-8")

    scenes = parse_conversation(conversation)

    manifest["script"] = {
        "insights": insights,
        "context": context,
        "visual_context": visual_context,
        "conversation_raw": conversation
    }
    manifest["scenes"] = scenes

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info(f"Script + manifest updated ({len(scenes)} scenes)")
    return manifest


# =========================
# CLI
# =========================
def main():
    parser = argparse.ArgumentParser(description="Generate script and update project manifest")
    parser.add_argument("project_name")
    args = parser.parse_args()
    create_script(args.project_name)

if __name__ == "__main__":
    create_script("office_convo_4")
