#!/usr/bin/env python3
"""Genera un video automáticamente a partir de un audio y unas imágenes.

El audio se transcribe, se divide en escenas de ~N segundos y cada escena se
empareja con la imagen más afín a lo que se dice (CLIP). Luego se ensambla el
video final con ese audio.

Ejemplo:
    python make_video.py --audio narracion.mp3 --images ./fotos --out video.mp4
"""

import argparse
import glob
import os
import sys
from pathlib import Path
from typing import List

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}


def gather_images(path: str) -> List[str]:
    """Devuelve las imágenes de una carpeta o de un patrón glob, ordenadas."""
    p = Path(path)
    if p.is_dir():
        files = [f for f in sorted(p.iterdir()) if f.suffix.lower() in IMAGE_EXTS]
    else:
        files = [Path(f) for f in sorted(glob.glob(path))]
        files = [f for f in files if f.suffix.lower() in IMAGE_EXTS]
    return [str(f) for f in files]


def parse_size(value: str):
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except Exception:
        raise argparse.ArgumentTypeError("El tamaño debe ser ANCHOxALTO, p. ej. 1920x1080")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio", required=True, help="Ruta del archivo de audio")
    ap.add_argument("--images", required=True, help="Carpeta o patrón glob con las imágenes")
    ap.add_argument("--out", default="output.mp4", help="Archivo de salida (por defecto output.mp4)")
    ap.add_argument("--scene-seconds", type=float, default=7.0, help="Duración aprox. de cada escena (def. 7)")
    ap.add_argument("--size", type=parse_size, default=(1920, 1080), help="Resolución ANCHOxALTO (def. 1920x1080)")
    ap.add_argument("--fps", type=int, default=30, help="Cuadros por segundo (def. 30)")
    ap.add_argument("--whisper-model", default="base", help="Modelo Whisper: tiny|base|small|medium|large-v3")
    ap.add_argument("--language", default=None, help="Idioma del audio (p. ej. es). Por defecto se autodetecta")
    ap.add_argument("--clip-model", default=None, help="Modelo CLIP de open_clip (def. multilingüe)")
    ap.add_argument("--clip-pretrained", default=None, help="Pesos preentrenados de open_clip")
    ap.add_argument("--allow-repeat", action="store_true", help="Permitir repetir la misma imagen en varias escenas")
    args = ap.parse_args(argv)

    if not os.path.exists(args.audio):
        sys.exit(f"No existe el audio: {args.audio}")

    images = gather_images(args.images)
    if not images:
        sys.exit(f"No se encontraron imágenes en: {args.images}")

    # Importes perezosos para que --help no requiera las dependencias pesadas.
    from moviepy import AudioFileClip

    from videogen.builder import build_video
    from videogen.matcher import DEFAULT_MODEL, DEFAULT_PRETRAINED, match_images
    from videogen.scenes import build_scenes
    from videogen.transcribe import transcribe

    clip_model = args.clip_model or DEFAULT_MODEL
    clip_pretrained = args.clip_pretrained or DEFAULT_PRETRAINED

    with AudioFileClip(args.audio) as a:
        duration = a.duration
    print(f"Audio: {duration:.1f}s | {len(images)} imágenes encontradas")

    print("Transcribiendo audio (Whisper)...")
    segments = transcribe(args.audio, model_size=args.whisper_model, language=args.language)

    scenes = build_scenes(segments, duration, scene_seconds=args.scene_seconds)
    print(f"{len(scenes)} escenas de ~{args.scene_seconds:.0f}s")

    print("Emparejando imágenes con lo que se dice (CLIP)...")
    assignments = match_images(
        scenes,
        images,
        model_name=clip_model,
        pretrained=clip_pretrained,
        allow_repeat=args.allow_repeat,
    )
    for i, (sc, img) in enumerate(zip(scenes, assignments), 1):
        print(f"  Escena {i:>3} [{sc.start:6.1f}-{sc.end:6.1f}s] -> {os.path.basename(img):<24} :: {sc.text[:48]!r}")

    print("Renderizando video...")
    build_video(scenes, assignments, args.audio, args.out, size=args.size, fps=args.fps)
    print(f"\n✓ Listo: {args.out}")


if __name__ == "__main__":
    main()
