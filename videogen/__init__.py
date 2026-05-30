"""videogen: genera videos automáticamente a partir de un audio y un conjunto
de imágenes.

El pipeline:
  1. transcribe.py  -> transcribe el audio (Whisper) con marcas de tiempo.
  2. scenes.py      -> agrupa la transcripción en escenas de ~N segundos.
  3. matcher.py     -> empareja cada escena con la imagen más afín usando CLIP.
  4. builder.py     -> ensambla el video (imágenes + audio) con MoviePy/ffmpeg.
"""

from .scenes import Scene, build_scenes

__all__ = ["Scene", "build_scenes"]
