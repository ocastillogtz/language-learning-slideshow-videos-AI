"""The local script path (Claude writes the script via the MCP): no OpenAI call at all.

Runs create_project + script_prompt + create_script(script=...) in a temporary
projects folder with an OpenAI client that fails on any request.
"""
import json

import pytest

import create_project as cp
import create_script as cs
import podcast
import utils_config


class _NoOpenAI:
    """Any attribute access chain ending in a call raises — proves no API use."""
    def __getattr__(self, name):
        return self

    def __call__(self, *a, **k):
        raise AssertionError("OpenAI was called on the local script path")


@pytest.fixture
def tmp_projects(tmp_path, monkeypatch):
    real = utils_config.load_config()

    def fake_load_config(*a, **k):
        cfg = dict(real)
        cfg["projects_dir"] = tmp_path
        return cfg

    for mod in (cp, cs, podcast):
        monkeypatch.setattr(mod, "load_config", fake_load_config)
    monkeypatch.setattr(cs, "client", _NoOpenAI())
    return tmp_path


def _podcast_script():
    return {
        "title": "Brezel Podcast: Test (B1) 🥨 #germanlearning #deutschlernen",
        "tags": "#germanlearning #deutschlernen",
        "insights": "Eine kurze Testfolge.",
        "main_background": "the podcast studio",
        "dialog": [
            {"text": "Hallo und herzlich willkommen beim Brezel Podcast!", "speaker": "Zahra",
             "setting": "studio", "example_id": "", "scene_visual": "", "scene_characters": "both"},
            {"text": "Heute geht es um *weil*.", "speaker": "Sani",
             "setting": "studio", "example_id": "", "scene_visual": "", "scene_characters": "both"},
            {"text": "Ich komme zu spät, _weil_ der Bus nicht _kommt_.", "speaker": "Sani",
             "setting": "example", "example_id": "bus",
             "scene_visual": "Sani waits at a bus stop in the rain, checking his watch.",
             "scene_characters": "speaker_only"},
            {"text": "Das Verb steht am Ende.", "speaker": "Zahra",
             "setting": "example", "example_id": "bus",
             "scene_visual": "Sani waits at a bus stop in the rain, checking his watch.",
             "scene_characters": "speaker_only"},
            {"text": "Bis zum nächsten Mal. Tschüss!", "speaker": "Zahra",
             "setting": "studio", "example_id": "", "scene_visual": "", "scene_characters": "both"},
        ],
        "podcast_shorts": [{"start": 1, "end": 3, "title": "weil (B1) 🥨 #shorts #deutschlernen",
                            "description": "Kurz erklärt.\nGanze Folge: {LINK}\n#deutsch"}],
    }


def test_prompt_then_supplied_podcast_script(tmp_projects):
    cp.create_project("pod_test", "podcast", "Konjunktionen", "weil", "B1", "")

    info = cs.script_prompt("pod_test", "Zahra", "Sani")
    assert info["project_type_key"] == "podcast" and info["cast"] == ["Zahra", "Sani"]
    assert "Brezel Podcast" in info["prompt"] and '"dialog"' in info["prompt"]
    assert any("podcast_shorts" in e for e in info["extra_fields"])

    m = cs.create_script("pod_test", "Zahra", "Sani", script=_podcast_script())
    gen = m["generation_config"]
    assert gen["script_source"] == "supplied"
    assert "dialog_auto_evaluation" not in gen
    assert m["video_info"]["title"].startswith("Brezel Podcast: Test")

    dialog = [s for s in m["scenes"] if "_dialog_index" in s]
    assert len(dialog) == 5
    assert [s["_podcast_setting"] for s in dialog] == ["studio", "studio", "example", "example", "studio"]
    # the second line of the "bus" example reuses the first one's image
    assert dialog[2]["image"] and dialog[3]["image"] is None

    assert m["podcast"]["shorts"][0]["start"] == 1 and m["podcast"]["shorts"][0]["end"] == 3
    saved = json.loads((tmp_projects / "pod_test" / "project_manifest.json").read_text(encoding="utf-8"))
    assert saved["scenes"] == m["scenes"]
    assert (tmp_projects / "pod_test" / "script.txt").exists()
    assert (tmp_projects / "pod_test" / "shorts.txt").exists()


def test_supplied_script_is_validated(tmp_projects):
    cp.create_project("pod_bad", "podcast", "Konjunktionen", "weil", "B1", "")
    bad = _podcast_script()
    bad["dialog"][0]["speaker"] = "Nobody"
    with pytest.raises(ValueError, match="not in the cast"):
        cs.create_script("pod_bad", "Zahra", "Sani", script=bad)
    with pytest.raises(ValueError, match="dialog"):
        cs.create_script("pod_bad", "Zahra", "Sani", script={"title": "x", "tags": "x", "insights": "x"})


def test_shadowing_needs_supplied_repetitions(tmp_projects):
    types = utils_config.load_project_types(utils_config.load_config()["assets_dir"])
    key = next(k for k, t in types.items()
               if (t.get("scene_builder_rules") or {}).get("include_repetition_section"))
    cp.create_project("shadow_test", key, "Beim Bäcker", "", "A2", "")
    script = {
        "title": "Test", "tags": "#deutsch", "insights": "Test.",
        "dialog": [{"text": t, "speaker": sp, "scene_visual": "At a bakery counter.",
                    "scene_characters": "speaker_only"}
                   for t, sp in [("Guten Morgen!", "Zahra"), ("Ich hätte gern zwei Brötchen.", "Sani"),
                                 ("Sonst noch etwas?", "Zahra"), ("Nein, danke.", "Sani")]],
    }
    info = cs.script_prompt("shadow_test", "Zahra", "Sani")
    assert any("repetitions" in e for e in info["extra_fields"])
    with pytest.raises(ValueError, match="repetitions"):
        cs.create_script("shadow_test", "Zahra", "Sani", script=script)

    script["repetitions"] = ["Ich hätte gern zwei Brötchen.", {"text": "Sonst noch etwas?"}, "Nein, danke."]
    m = cs.create_script("shadow_test", "Zahra", "Sani", script=script)
    spoken = [s["audio"]["tts_text"] for s in m["scenes"] if (s.get("audio") or {}).get("type") == "tts"]
    assert spoken.count("Ich hätte gern zwei Brötchen.") >= 2   # dialog line + its repetition
