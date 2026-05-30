"""Pruebas de la lógica de escenas (Python puro, sin modelos pesados)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from videogen.scenes import build_scenes


def approx(a, b, tol=1e-6):
    return abs(a - b) < tol


def test_scenes_cover_full_duration():
    segments = [(0.0, 3.0, "hola"), (3.0, 6.0, "mundo"), (6.0, 9.0, "adios")]
    scenes = build_scenes(segments, total_duration=9.0, scene_seconds=7.0)
    assert approx(scenes[0].start, 0.0)
    assert approx(scenes[-1].end, 9.0)
    # contiguas
    for a, b in zip(scenes, scenes[1:]):
        assert approx(a.end, b.start)


def test_groups_by_scene_seconds():
    # 10 segmentos de 1s; con escenas de ~3s deberían salir varias escenas.
    segments = [(float(i), float(i + 1), f"t{i}") for i in range(10)]
    scenes = build_scenes(segments, total_duration=10.0, scene_seconds=3.0)
    assert len(scenes) >= 3
    assert approx(scenes[-1].end, 10.0)
    # cada escena (salvo quizá la última) dura ~>=3s
    for sc in scenes[:-1]:
        assert sc.duration >= 3.0 - 1e-6


def test_no_segments_chunks_by_time():
    scenes = build_scenes([], total_duration=20.0, scene_seconds=7.0)
    assert len(scenes) == 3  # 7 + 7 + 6
    assert approx(scenes[0].duration, 7.0)
    assert approx(scenes[-1].end, 20.0)
    assert all(sc.text == "" for sc in scenes)


def test_tail_silence_extends_last_scene():
    # El habla termina en 5s pero el audio dura 12s: la última escena se estira.
    segments = [(0.0, 5.0, "habla")]
    scenes = build_scenes(segments, total_duration=12.0, scene_seconds=7.0)
    assert approx(scenes[-1].end, 12.0)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(tests)} pruebas pasaron.")
