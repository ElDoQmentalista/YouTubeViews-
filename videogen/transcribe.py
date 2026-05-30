"""Transcripción del audio con faster-whisper.

Devuelve una lista de segmentos ``(inicio, fin, texto)`` con marcas de tiempo.
El modelo se descarga automáticamente la primera vez.
"""

from typing import List, Optional

from .scenes import Segment


def transcribe(
    audio_path: str,
    model_size: str = "base",
    language: Optional[str] = None,
    compute_type: str = "int8",
    device: str = "cpu",
) -> List[Segment]:
    """Transcribe ``audio_path`` y devuelve segmentos con tiempos.

    - ``model_size``: tiny | base | small | medium | large-v3 (más grande =
      más preciso pero más lento).
    - ``language``: código ISO (p. ej. "es"). Si es None, Whisper lo detecta.
    """
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,  # ignora silencios largos
    )
    return [(seg.start, seg.end, seg.text.strip()) for seg in segments]
