"""FFmpeg-free tests for assemble_video's command-line batching (WinError 206 guard).

A 528-scene podcast episode once failed to assemble because the `-i <path>` list
alone exceeded the Windows 32,767-char command-line cap. These tests check that
_concat_batches keeps every FFmpeg call bounded, whatever the project size.
"""
import subprocess

import assemble_video as av

LONG_DIR = r"C:\Users\SomeoneWithALongName\Documents\germanLearningVidsAIPowered\projects\a_very_long_project_name_for_testing\videos"


def _clips(n, folder=LONG_DIR):
    return [rf"{folder}\scene_{i:03d}.mp4" for i in range(n)]


def _worst_case_cmd(paths, has_aud):
    """Build the argv exactly like ffmpeg_concat_scenes does for one batch."""
    inputs = [t for p in paths for t in ("-i", p)]
    extra = [t for a in has_aud if not a
             for t in ("-f", "lavfi", "-t", "1234.567", "-i", "anullsrc=r=44100:cl=stereo")]
    return (["ffmpeg", "-y"] + inputs + extra
            + ["-filter_complex_script", r"C:\Users\x\AppData\Local\Temp\tmpabcdefgh.txt",
               "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "fast",
               "-crf", "18", "-r", "30", "-c:a", "aac", "-b:a", "192k",
               LONG_DIR + r"\concat_tmp_part00.mp4"])


def _check(paths, has_aud):
    batches = av._concat_batches(paths, has_aud)
    # contiguous, in order, covering every clip exactly once
    assert batches[0][0] == 0 and batches[-1][1] == len(paths), batches
    assert all(a[1] == b[0] for a, b in zip(batches, batches[1:])), batches
    for s, e in batches:
        assert 0 < e - s <= av.MAX_CONCAT_INPUTS, (s, e)
        cmd = _worst_case_cmd(paths[s:e], has_aud[s:e])
        assert len(subprocess.list2cmdline(cmd)) < av.WIN_CMDLINE_LIMIT, (s, e)
    return batches


def test_small_project_is_one_batch():
    paths = _clips(40)
    assert av._concat_batches(paths, [True] * 40) == [(0, 40)]


def test_podcast_episode_528_scenes():
    # dialog clips (with audio) alternate with silent pause clips, like the podcast
    paths = _clips(528)
    has_aud = [i % 2 == 0 for i in range(528)]
    assert len(_check(paths, has_aud)) >= 2


def test_all_silent_long_paths():
    paths = _clips(2000, LONG_DIR + r"\an_extra_nested_folder_to_make_paths_even_longer")
    _check(paths, [False] * 2000)


def test_parts_pass_is_bounded_too():
    # The second pass concatenates the part files; with thousands of scenes the
    # part list itself must batch again rather than overflow.
    paths = _clips(5000)
    batches = _check(paths, [False] * 5000)
    part_paths = [LONG_DIR + rf"\concat_tmp_part{n:02d}.mp4" for n in range(len(batches))]
    _check(part_paths, [True] * len(part_paths))
