from __future__ import annotations

import numpy as np
from PIL import Image


def crop_subject(image: Image.Image) -> Image.Image:
    """Crop likely foreground subject and reduce face influence at query time."""
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
        return suppress_likely_face(_center_crop(rgb))

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
        return suppress_likely_face(rgb)
    if area_ratio > 0.92:
        return suppress_likely_face(_center_crop(rgb))

    pad = int(max(crop_w, crop_h) * 0.08)
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(width, right + pad)
    bottom = min(height, bottom + pad)
    return suppress_likely_face(rgb.crop((left, top, right, bottom)))


def suppress_likely_face(image: Image.Image) -> Image.Image:
    """Mask a model face-like skin region so clothing/product details dominate the embedding."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 80 or height < 80:
        return rgb

    max_side = 384
    scale = min(1.0, max_side / max(width, height))
    work = rgb
    if scale < 1.0:
        work = rgb.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.BILINEAR)

    candidate = _likely_face_bbox(work)
    if candidate is None:
        return rgb

    left, top, right, bottom = candidate
    inv_scale = 1.0 / scale
    left = int(left * inv_scale)
    top = int(top * inv_scale)
    right = int(right * inv_scale)
    bottom = int(bottom * inv_scale)

    face_w = right - left
    face_h = bottom - top
    pad_x = int(face_w * 0.25)
    pad_y = int(face_h * 0.18)
    left = max(0, left - pad_x)
    top = max(0, top - pad_y)
    right = min(width, right + pad_x)
    bottom = min(height, bottom + pad_y)

    fill = _edge_color(rgb)
    result = rgb.copy()
    result.paste(fill, (left, top, right, bottom))
    return result


def _likely_face_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    arr = np.asarray(image).astype(np.uint8)
    height, width, _ = arr.shape
    skin = _skin_mask(arr)
    if not skin.any():
        return None

    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    for left, top, right, bottom, area in _connected_components(skin):
        comp_w = right - left
        comp_h = bottom - top
        if comp_w < max(10, width * 0.04) or comp_h < max(12, height * 0.05):
            continue
        area_ratio = area / float(width * height)
        if not 0.01 <= area_ratio <= 0.18:
            continue
        aspect = comp_w / max(1, comp_h)
        if not 0.45 <= aspect <= 1.55:
            continue

        center_x = (left + right) / 2.0 / width
        center_y = (top + bottom) / 2.0 / height
        if center_y > 0.58:
            continue
        if not 0.18 <= center_x <= 0.82:
            continue
        if not _has_face_contrast(arr, (left, top, right, bottom)):
            continue
        if not _has_lower_non_skin_subject(skin, bottom):
            continue

        centrality = 1.0 - abs(center_x - 0.5)
        upper_bonus = 1.0 - center_y
        score = area_ratio * 8.0 + centrality + upper_bonus
        candidates.append((score, (left, top, right, bottom)))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _skin_mask(arr: np.ndarray) -> np.ndarray:
    r = arr[:, :, 0].astype(np.int16)
    g = arr[:, :, 1].astype(np.int16)
    b = arr[:, :, 2].astype(np.int16)
    max_rgb = np.maximum(np.maximum(r, g), b)
    min_rgb = np.minimum(np.minimum(r, g), b)
    return (
        (r > 70)
        & (g > 35)
        & (b > 20)
        & ((max_rgb - min_rgb) > 12)
        & (r > g)
        & (r > b)
        & ((r - g) < 85)
    )


def _connected_components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    components: list[tuple[int, int, int, int, int]] = []
    for y in range(height):
        xs = np.where(mask[y] & ~seen[y])[0]
        for x0 in xs:
            if seen[y, x0]:
                continue
            stack = [(x0, y)]
            seen[y, x0] = True
            left = right = x0
            top = bottom = y
            area = 0
            while stack:
                x, current_y = stack.pop()
                area += 1
                left = min(left, x)
                right = max(right, x)
                top = min(top, current_y)
                bottom = max(bottom, current_y)
                for nx, ny in ((x - 1, current_y), (x + 1, current_y), (x, current_y - 1), (x, current_y + 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((nx, ny))
            components.append((left, top, right + 1, bottom + 1, area))
    return components


def _has_lower_non_skin_subject(skin: np.ndarray, face_bottom: int) -> bool:
    height, _ = skin.shape
    lower_top = min(height - 1, face_bottom + max(4, height // 40))
    if lower_top >= height:
        return False
    lower = skin[lower_top:, :]
    return lower.size > 0 and float(lower.mean()) < 0.35


def _has_face_contrast(arr: np.ndarray, bbox: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = bbox
    crop = arr[top:bottom, left:right, :]
    if crop.size == 0:
        return False
    luminance = crop.astype(np.float32).mean(axis=2)
    dark_ratio = float((luminance < 80).mean())
    return dark_ratio >= 0.006


def _edge_color(image: Image.Image) -> tuple[int, int, int]:
    arr = np.asarray(image).astype(np.uint8)
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
    fill = np.median(border, axis=0).astype(np.uint8)
    return int(fill[0]), int(fill[1]), int(fill[2])


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
