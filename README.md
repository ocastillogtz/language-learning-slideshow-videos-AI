# AI-Powered Educational Video Generator

An automated pipeline for creating high-quality educational videos (specifically tailored for language learning) using AI-generated content. This system transforms simple concepts into fully composed videos ready for platforms like YouTube.

## 🚀 Overview

This project automates the entire content creation lifecycle for educational videos. By providing basic parameters (characters, locations, and learning objectives), the pipeline handles scriptwriting, voiceovers, images, subtitles, and video composition automatically.

## 🏗️ Pipeline Architecture

The generation process follows a sequential, modular pipeline where each step relies on the output of the previous one, coordinated by a central manifest file.

### 1. Project Initialization (`create_project.py`)
- Creates a project directory structure
- Initializes a `project_manifest.json` file that serves as the "Single Source of Truth"
- Sets up all necessary folders for audio, images, and videos

### 2. Script Generation (`create_script.py`)
- Uses LLMs to generate structured narratives
- Creates dialogue between characters
- Incorporates learning objectives and educational content
- Generates metadata including character descriptions and location details

### 3. Audio Synthesis (`create_audio.py`)
- Generates high-quality Text-to-Speech (TTS) audio
- Creates separate audio files for each character and narrator
- Ensures distinct voices for different roles
- Handles repetition sections for shadowing practice

### 4. Visual Asset Generation (`create_images.py`)
- Interfaces with image generation models to create consistent visual assets
- Generates character portraits and location backgrounds
- Creates over-the-shoulder shots and cutaway images
- Implements caching to avoid regenerating identical assets

### 5. Video Composition (`create_video.py` & `assemble_video.py`)
- Creates individual video clips with synchronized audio and subtitles
- Stitches together all clips into a final production
- Adds background music and branding elements
- Applies transitions and visual effects

### 6. Distribution (`upload_video.py`)
- Automatically uploads finished videos to YouTube
- Includes optimized titles, descriptions, and tags
- Handles authentication and credential management

## 📄 The Manifest File

The `project_manifest.json` is the core orchestrator of the project. It tracks every asset, path, and piece of text generated during the pipeline, allowing for:
- Interrupting and resuming the pipeline
- Re-running specific modules without re-generating everything
- Maintaining consistency across all generated content

## 🛠️ Requirements

- Python 3.x
- OpenAI API Key (for script and image generation)
- ElevenLabs API Key (for audio generation)
- FFmpeg (for video processing)
- Google Cloud Credentials (for YouTube uploading)
- FAL AI API Key (for image generation)

## 📦 Installation

1. Clone the repository
2. Install required packages: `pip install -r requirements.txt`
3. Set up your API keys in `config.ini`
4. Configure paths in `config.ini` to match your system

## 🎯 Usage

Run the main script to create a new project:
