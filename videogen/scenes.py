"""Agrupa la transcripción en escenas de ~N segundos.

Esta parte es Python puro (sin dependencias pesadas) para poder probarla
de forma aislada.
"""

from dataclasses import dataclass
from typing import List, Sequence, Tuple

# Un segmento de transcripción: (inicio_seg, fin_seg, texto)
Segment = Tuple[float, float, str]


@dataclass
class Scene:
    """Un tramo del video que mostrará una sola imagen."""

    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def build_scenes(
    segments: Sequence[Segment],
    total_duration: float,
    scene_seconds: float = 7.0,
) -> List[Scene]:
    """Agrupa los segmentos de transcripción en escenas contiguas.

    En lugar de cortar a ciegas cada 7 s (lo que partiría frases a la mitad),
    acumula segmentos hasta superar ``scene_seconds`` y cierra la escena en el
    final del último segmento. Así el texto de cada escena queda coherente.

    Las escenas resultantes cubren de forma contigua ``[0, total_duration]``,
    de modo que coinciden exactamente con el audio.
    """
    if scene_seconds <= 0:
        raise ValueError("scene_seconds debe ser > 0")
    if total_duration <= 0:
        raise ValueError("total_duration debe ser > 0")

    scenes: List[Scene] = []

    # Sin habla (o sin transcripción): trocea por tiempo a secas.
    if not segments:
        t = 0.0
        while t < total_duration - 1e-6:
            end = min(t + scene_seconds, total_duration)
            scenes.append(Scene(t, end, ""))
            t = end
        if not scenes:
            scenes.append(Scene(0.0, total_duration, ""))
        return scenes

    cur_start = 0.0
    cur_texts: List[str] = []
    for start, end, text in segments:
        if text:
            cur_texts.append(text.strip())
        if end - cur_start >= scene_seconds:
            scenes.append(Scene(cur_start, end, " ".join(cur_texts).strip()))
            cur_start = end
            cur_texts = []

    # Cola final (texto sobrante o ninguna escena creada todavía).
    if cur_texts or not scenes:
        scenes.append(
            Scene(cur_start, max(cur_start, total_duration), " ".join(cur_texts).strip())
        )

    # Hacer las escenas contiguas y ajustarlas a la duración real del audio.
    scenes[0].start = 0.0
    for i in range(1, len(scenes)):
        scenes[i].start = scenes[i - 1].end
    scenes[-1].end = max(scenes[-1].start, total_duration)

    # Descartar escenas de duración nula/negativa por redondeos.
    return [sc for sc in scenes if sc.duration > 1e-3]
