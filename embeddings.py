"""
CLIP-based image embeddings for visual search.
Model is loaded once on first use (~340 MB download on first run).
"""
import numpy as np
import torch
from PIL import Image

_model = None
_processor = None


def _load():
    global _model, _processor
    if _model is None:
        from transformers import CLIPModel, CLIPProcessor
        _model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        _processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        _model.eval()
    return _model, _processor


def embed_image_file(path):
    """Return a normalised float32 numpy embedding for the image at path."""
    model, processor = _load()
    img    = Image.open(path).convert("RGB")
    inputs = processor(images=img, return_tensors="pt")
    with torch.no_grad():
        result = model.get_image_features(pixel_values=inputs["pixel_values"])
    # transformers >= 5.x returns BaseModelOutputWithPooling where pooler_output
    # is the already-projected 512-dim embedding; older versions return a tensor
    feat = result.pooler_output if hasattr(result, "pooler_output") else result
    feat = feat / feat.norm(dim=-1, keepdim=True)
    return feat.cpu().numpy().flatten().astype(np.float32)


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two normalised embeddings."""
    return float(np.dot(a, b))


def to_blob(arr: np.ndarray) -> bytes:
    return arr.astype(np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
