### No longer maintained

# Usage
```sh
 $ python youtube.py [visits] [youtubeLinks.txt] [minWatch] [maxWatch]
 ```

# Help
 - **visits** The amount of visits per video
 - **youtubeLinks** The file that contains the Youtube links; one link per line
 - **minWatch** The minimum watch time in seconds
 - **maxWatch** The maximum watch time in seconds

# Example
 - python youtube.py 300 urls.txt 38 65

---

# Generador de video (videogen)

Crea un video automáticamente a partir de **un audio** y **un conjunto de
imágenes**. El audio se transcribe, se divide en escenas de ~7 segundos y cada
escena se empareja con la imagen que mejor coincide con lo que se dice usando
IA (CLIP, multilingüe por defecto para que funcione con audio en español).

## Instalación
```sh
pip install -r requirements-videogen.txt
```
(La primera ejecución descarga los modelos de Whisper y CLIP, y ffmpeg.)

## Uso
```sh
python make_video.py --audio narracion.mp3 --images ./fotos --out video.mp4
```

## Opciones
 - **--audio** Ruta del archivo de audio (mp3, wav, m4a...).
 - **--images** Carpeta o patrón glob con las imágenes.
 - **--out** Archivo de salida (por defecto `output.mp4`).
 - **--scene-seconds** Duración aprox. de cada escena (por defecto `7`).
 - **--size** Resolución `ANCHOxALTO` (por defecto `1920x1080`).
 - **--fps** Cuadros por segundo (por defecto `30`).
 - **--whisper-model** `tiny|base|small|medium|large-v3` (por defecto `base`).
 - **--language** Idioma del audio, p. ej. `es` (por defecto se autodetecta).
 - **--allow-repeat** Permite repetir una imagen en varias escenas.

## Cómo funciona
 1. `videogen/transcribe.py` transcribe el audio con Whisper (con tiempos).
 2. `videogen/scenes.py` agrupa la transcripción en escenas de ~N segundos.
 3. `videogen/matcher.py` empareja cada escena con la imagen más afín (CLIP).
 4. `videogen/builder.py` ensambla el video (imágenes + audio) con MoviePy.
