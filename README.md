# Language Pipeline

**Turn an idea into a finished language-learning video — script, voices, illustrations, subtitles,
music and upload — from one browser app.**

You describe a scene ("two friends order coffee"), pick a video type and a level, and the pipeline
writes the dialog, voices it, illustrates every line in your channel's art style, renders subtitled
clips and assembles a vertical Short or a horizontal YouTube video, ready to upload to YouTube,
Instagram and Facebook.

It was built for a German-learning channel and now works for **20 languages**: each language or
channel lives in its own **workspace** with its own characters, art style, prompts and projects.

<p align="center">
  <img src="readme_resources/ui_projects.jpg" width="780" alt="Projects view with the pipeline steps">
</p>

---

## What it can do

- **Write the script** with GPT, or let Claude write it for free through the built-in MCP bridge.
- **Voice it** with ElevenLabs, one voice per character.
- **Illustrate every line** with fal.ai, keeping your recurring characters on-model and the setting
  consistent across scenes.
- **Render and assemble**: subtitles with highlighted vocabulary, shadowing "repeat now" pauses,
  quizzes with a countdown, grammar-annotated reading videos, background music, intro clips.
- **Upload** to YouTube, Instagram (Reels) and Facebook with titles, descriptions and hashtags
  filled in from the script.
- **Run several channels**: switch workspace from the header — German, Spanish, Japanese… each with its
  own settings.
- **Manage assets visually**: characters (including art generation in your series' style), locations,
  shared background music with a volume tool, SFX and branding clips.

### Video types

| Short (9:16) | Long (16:9) | Special |
|---|---|---|
| Shadowing (with repetitions) · Story · Word learning · Register phrases · Grammar pairs · Song quiz · Preposition quiz · Fill-in-the-blank quiz | Long versions of the dialog types · Podcast episode (+ vertical Shorts) | Reading together (story → annotated parts) · Song (lyric video from an audio file) · Promotional (character speaks) |

Types are data, not code: edit their prompts or add new ones in **Settings → Project types**.

---

## Quick start (Windows)

```bat
git clone https://github.com/ocastillogtz/language-learning-slideshow-videos-AI.git
cd language-learning-slideshow-videos-AI
install_dependencies.bat
copy .env.example .env
```

Put your OpenAI, ElevenLabs and fal.ai keys in `.env`, then start the app:

```bat
launch.bat
```

The browser opens at <http://127.0.0.1:5000>. On first start a default workspace is created — set its
language, channel name and art style in **Settings**, add your characters in **Assets**, and press
**New Project**. The full walkthrough is in [Getting started](docs/GETTING_STARTED.md).

---

## Documentation

| Guide | For |
|---|---|
| [**Getting started**](docs/GETTING_STARTED.md) | Installing, API keys, and setting up a workspace through **Settings** (language, art style, labels, characters, music) |
| [**Using it**](docs/USAGE.md) | Making a video end to end: new project → script → audio → images → render → assemble → upload, plus the special video types and the Claude (MCP) workflow |
| [**How it is built**](docs/ARCHITECTURE.md) | Architecture, data model (SQLite + project manifests), folder layout, pipeline modules, and how to extend it |
| [Full reference](docs/REFERENCE.md) | Every pipeline step, config key, API endpoint and CLI command in detail |

---

## Built with

Python · Flask · React (no build step) · SQLite · MoviePy + FFmpeg · Playwright ·
OpenAI · ElevenLabs · fal.ai · YouTube Data API · Meta Graph API · MCP (Claude)

Runs locally on Windows. Your API keys, credentials and media never leave your machine except for the
calls to the services above.
