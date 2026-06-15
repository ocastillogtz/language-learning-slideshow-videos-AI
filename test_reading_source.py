"""Network-free tests for create_reading_source (split, chunk, scenes, casting, enrich)."""
import sys, types

m = types.ModuleType("openai"); m.OpenAI = lambda **k: None; sys.modules["openai"] = m
d = types.ModuleType("dotenv"); d.load_dotenv = lambda *a, **k: None; sys.modules["dotenv"] = d

import create_reading_source as crs


def _passed(x): print(f"  PASS  {x}")
def _fail(x): print(f"  FAIL  {x}"); _fail.count += 1
_fail.count = 0


def test_naive_split_basic():
    s = crs._naive_split("Es war einmal ein Fuchs. Er hatte Hunger! Was nun?")
    assert s == ["Es war einmal ein Fuchs.", "Er hatte Hunger!", "Was nun?"], s
    _passed("splits on . ! ?")


def test_naive_split_long_sentence():
    long = ("Der alte Mueller ging am Morgen in die Stadt, "
            "weil er Mehl verkaufen wollte, und er nahm seinen Esel mit, "
            "der schwer beladen war.")
    out = crs._naive_split(long, max_words=8)
    assert len(out) >= 3 and all(len(x.split()) <= 14 for x in out), out
    _passed("breaks long sentence at clause boundaries")


def test_chunk_into_parts():
    parts = crs.chunk_into_parts([f"s{i}" for i in range(1, 14)], per_part=6)
    assert [len(p) for p in parts] == [6, 6, 1]
    _passed("chunks into parts of 6 with remainder")


def test_modernize_fallback():
    r = crs.modernize_and_split("Es giebt einen Fuchs. Er thut Boeses.", level="B1")
    assert r["sentences"] == ["Es giebt einen Fuchs.", "Er thut Boeses."]
    _passed("modernize_and_split falls back gracefully")


def test_build_reading_scenes():
    scenes = crs.build_reading_scenes(["Satz eins.", "Satz zwei.", "Satz drei."],
                                      narrator_voice="VID", per_part=2)
    tts = [s for s in scenes if s.get("audio") and s["audio"]["type"] == "tts"]
    assert len(tts) == 3
    assert tts[0]["audio"]["voice_id"] == "VID"
    assert tts[0]["_part_index"] == 0 and tts[2]["_part_index"] == 1
    _passed("build_reading_scenes: scene+pause per sentence, part indexing")


def test_clean_cast():
    cast = crs._clean_cast([
        {"name": "Fuchs", "kind": "animal", "description": "red fox, upright, vest"},
        {"name": "X"},                       # no description -> dropped
        {"name": "Bär", "kind": "weird", "description": "brown bear"},  # bad kind -> human
    ])
    assert [c["name"] for c in cast] == ["Fuchs", "Bär"], cast
    assert cast[0]["kind"] == "animal" and cast[1]["kind"] == "human"
    _passed("_clean_cast filters + normalizes kinds")


def test_clean_plans_fills_gaps():
    plans = crs._clean_plans([{"index": 1, "scene_visual": "a forest", "characters": ["Fuchs"]}], 3)
    assert [p["index"] for p in plans] == [0, 1, 2]
    assert plans[0]["scene_visual"] == "" and plans[1]["scene_visual"] == "a forest"
    _passed("_clean_plans fills missing sentence indices")


def test_reading_image_prompt():
    p = crs._reading_image_prompt("A fox at dawn", ["Fuchs: red fox upright"],
                                  style_tokens="flat style", framing_tokens="9:16")
    assert "A fox at dawn" in p and "Fuchs: red fox upright" in p
    assert "flat style" in p and "FRAMING: 9:16" in p
    assert "no watermarks" in p
    _passed("_reading_image_prompt assembles style+framing+scene+cast")


def test_enrich_reading_scenes():
    scenes = crs.build_reading_scenes(["Der Fuchs läuft.", "Stille."], per_part=6)
    analysis = {
        "characters": [{"name": "Fuchs", "kind": "animal", "description": "red fox upright"}],
        "sentences": [
            {"index": 0, "scene_visual": "A red fox runs through grass", "characters": ["Fuchs"]},
            {"index": 1, "scene_visual": "", "characters": []},   # no visual -> no image
        ],
    }
    crs.enrich_reading_scenes(scenes, analysis, style_tokens="S", framing_tokens="F")
    tts = [s for s in scenes if s.get("audio")]
    assert tts[0]["scene_visual"] == "A red fox runs through grass"
    assert tts[0]["_cast"] == ["Fuchs"]
    assert tts[0]["image"] and tts[0]["image"]["reference_type"] == "none"
    assert "red fox upright" in tts[0]["image"]["prompt_to_create"]
    assert tts[0]["characters"] == [], "must not set characters[] (would add speaker icon)"
    assert tts[1]["image"] is None, "empty scene_visual -> no image"
    _passed("enrich_reading_scenes attaches visuals/prompts, skips empty, keeps characters[] empty")


def test_analyze_story_fallback():
    a = crs.analyze_story(["S1.", "S2."], level="B1")
    assert a["characters"] == []
    assert [p["index"] for p in a["sentences"]] == [0, 1]
    _passed("analyze_story falls back to empty plans for all sentences")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} tests\n")
    for t in tests:
        try:
            t()
        except AssertionError as e:
            _fail(f"{t.__name__}: {e}")
        except Exception as e:
            _fail(f"{t.__name__}: unexpected {e!r}")
    print()
    if _fail.count:
        print(f"{_fail.count} FAILED"); sys.exit(1)
    print("All tests passed.")
