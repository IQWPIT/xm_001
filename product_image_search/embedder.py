from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import AutoImageProcessor, AutoModel

from product_image_search.config import Settings


class DinoV2Embedder:
    vector_size = 384

    def __init__(self, settings: Settings):
        self.device = self._resolve_device(settings.device)
        self.processor = AutoImageProcessor.from_pretrained(settings.model_name)
        self.model = AutoModel.from_pretrained(settings.model_name).to(self.device)
        self.model.eval()

    @staticmethod
    def _resolve_device(device: str) -> torch.device:
        if device != "auto":
            return torch.device(device)
        if torch.cuda.is_available():
            return torch.device("cuda")
        if torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")

    @torch.inference_mode()
    def encode(self, images: Sequence[Image.Image]) -> np.ndarray:
        if not images:
            return np.empty((0, self.vector_size), dtype=np.float32)

        inputs = self.processor(images=list(images), return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        outputs = self.model(**inputs)
        features = outputs.last_hidden_state[:, 0, :]
        features = F.normalize(features, p=2, dim=1)
        return features.detach().cpu().numpy().astype(np.float32)
