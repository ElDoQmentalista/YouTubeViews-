"""Emparejamiento imagen <-> texto con CLIP (open_clip).

Para cada escena se calcula la similitud entre el texto de lo que se dice y
cada imagen, y se elige la imagen más afín. Por defecto se usa un modelo CLIP
multilingüe (entiende español), porque el CLIP estándar solo razona en inglés.
"""

from typing import List, Sequence

from .scenes import Scene

# Modelo multilingüe por defecto: empareja bien texto en español con imágenes.
DEFAULT_MODEL = "xlm-roberta-base-ViT-B-32"
DEFAULT_PRETRAINED = "laion5b_s13b_b90k"


def match_images(
    scenes: Sequence[Scene],
    image_paths: Sequence[str],
    model_name: str = DEFAULT_MODEL,
    pretrained: str = DEFAULT_PRETRAINED,
    allow_repeat: bool = False,
) -> List[str]:
    """Devuelve, para cada escena, la ruta de la imagen elegida.

    - ``allow_repeat=False``: evita repetir imágenes mientras queden sin usar;
      cuando se agotan todas, vuelve a permitirlas (ciclo).
    - ``allow_repeat=True``: siempre elige la imagen más afín aunque se repita.
    """
    import open_clip
    import torch
    from PIL import Image

    model, _, preprocess = open_clip.create_model_and_transforms(
        model_name, pretrained=pretrained
    )
    tokenizer = open_clip.get_tokenizer(model_name)
    model.eval()

    # Codificar todas las imágenes una sola vez.
    image_features = []
    for path in image_paths:
        img = preprocess(Image.open(path).convert("RGB")).unsqueeze(0)
        with torch.no_grad():
            feat = model.encode_image(img)
            feat /= feat.norm(dim=-1, keepdim=True)
        image_features.append(feat)
    image_features = torch.cat(image_features)  # [N, D]

    assignments: List[str] = []
    used: set = set()
    for scene in scenes:
        text = scene.text.strip() or "una imagen"
        tokens = tokenizer([text])
        with torch.no_grad():
            text_feat = model.encode_text(tokens)
            text_feat /= text_feat.norm(dim=-1, keepdim=True)
        sims = (text_feat @ image_features.T).squeeze(0)  # [N]
        order = sims.argsort(descending=True).tolist()

        choice = order[0]
        if not allow_repeat:
            for idx in order:
                if idx not in used:
                    choice = idx
                    break
            used.add(choice)
            if len(used) >= len(image_paths):
                used.clear()  # todas usadas: reiniciar el ciclo
        assignments.append(image_paths[choice])

    return assignments
