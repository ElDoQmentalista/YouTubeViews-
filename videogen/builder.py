"""Ensamblado final del video con MoviePy (ffmpeg).

Toma las escenas + la imagen asignada a cada una y produce un .mp4 con el
audio original. Cada imagen se ajusta al tamaño objetivo recortando al centro
(estilo "cover") para que no haya bordes negros.
"""

from typing import List, Sequence, Tuple

from .scenes import Scene


def _fit_cover(clip, size: Tuple[int, int]):
    """Escala la imagen para cubrir ``size`` y recorta el sobrante al centro."""
    target_w, target_h = size
    cw, ch = clip.size
    scale = max(target_w / cw, target_h / ch)
    clip = clip.resized(scale)
    cw, ch = clip.size
    return clip.cropped(
        x_center=cw / 2, y_center=ch / 2, width=target_w, height=target_h
    )


def build_video(
    scenes: Sequence[Scene],
    image_assignments: Sequence[str],
    audio_path: str,
    out_path: str = "output.mp4",
    size: Tuple[int, int] = (1920, 1080),
    fps: int = 30,
) -> str:
    """Construye el video y lo escribe en ``out_path``. Devuelve la ruta."""
    from moviepy import AudioFileClip, ImageClip, concatenate_videoclips

    if len(scenes) != len(image_assignments):
        raise ValueError("scenes e image_assignments deben tener igual longitud")

    clips: List = []
    for scene, image in zip(scenes, image_assignments):
        clip = ImageClip(image).with_duration(scene.duration)
        clips.append(_fit_cover(clip, size))

    video = concatenate_videoclips(clips, method="chain")
    audio = AudioFileClip(audio_path)
    video = video.with_audio(audio).with_duration(audio.duration)

    video.write_videofile(
        out_path,
        fps=fps,
        codec="libx264",
        audio_codec="aac",
    )
    audio.close()
    video.close()
    return out_path
