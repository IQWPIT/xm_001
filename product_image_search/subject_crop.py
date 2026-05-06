from __future__ import annotations

import numpy as np
from PIL import Image


def crop_subject(image: Image.Image) -> Image.Image:
    """Crop likely foreground subject to reduce background influence at query time."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 32 or height < 32:
        return rgb

    work = rgb.copy()
    max_side = 512
    scale = min(1.0, max_side / max(width, height))
    if scale < 1.0:
        work = rgb.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.BILINEAR)

    bbox = _foreground_bbox(work)
    if bbox is None:
        return _center_crop(rgb)

    left, top, right, bottom = bbox
    inv_scale = 1.0 / scale
    left = int(left * inv_scale)
    top = int(top * inv_scale)
    right = int(right * inv_scale)
    bottom = int(bottom * inv_scale)

    crop_w = right - left
    crop_h = bottom - top
    area_ratio = (crop_w * crop_h) / max(1, width * height)
    if area_ratio < 0.02:
        return rgb
    if area_ratio > 0.92:
        return _center_crop(rgb)

    pad = int(max(crop_w, crop_h) * 0.08)
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(width, right + pad)
    bottom = min(height, bottom + pad)
    return rgb.crop((left, top, right, bottom))


def _foreground_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    arr = np.asarray(image).astype(np.int16)
    height, width, _ = arr.shape
    edge = max(2, min(width, height) // 24)
    border = np.concatenate(
        [
            arr[:edge, :, :].reshape(-1, 3),
            arr[-edge:, :, :].reshape(-1, 3),
            arr[:, :edge, :].reshape(-1, 3),
            arr[:, -edge:, :].reshape(-1, 3),
        ],
        axis=0,
    )
    background = np.median(border, axis=0)
    diff = np.linalg.norm(arr - background, axis=2)
    border_diff = np.linalg.norm(border - background, axis=1)
    threshold = max(28.0, float(np.percentile(border_diff, 95)) + 12.0)
    mask = diff > threshold

    # Ignore tiny specks by requiring enough foreground pixels per row/column.
    row_hits = mask.mean(axis=1)
    col_hits = mask.mean(axis=0)
    rows = np.where(row_hits > 0.01)[0]
    cols = np.where(col_hits > 0.01)[0]
    if rows.size == 0 or cols.size == 0:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1] + 1), int(rows[-1] + 1)


def _center_crop(image: Image.Image, ratio: float = 0.82) -> Image.Image:
    width, height = image.size
    crop_w = max(1, int(width * ratio))
    crop_h = max(1, int(height * ratio))
    left = (width - crop_w) // 2
    top = (height - crop_h) // 2
    return image.crop((left, top, left + crop_w, top + crop_h))
