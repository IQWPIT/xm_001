from __future__ import annotations

from io import BytesIO

import requests
from minio import Minio
from PIL import Image, ImageOps, UnidentifiedImageError

from product_image_search.config import Settings


def build_minio_client(settings: Settings) -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_minio_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def open_rgb_image(data: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("bad image") from exc
    return image.convert("RGB")


def read_url_image(url: str, timeout_seconds: int) -> Image.Image:
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return open_rgb_image(response.content)


def read_minio_image(client: Minio, bucket: str, object_name: str) -> Image.Image:
    response = client.get_object(bucket, object_name)
    try:
        return open_rgb_image(response.read())
    finally:
        response.close()
        response.release_conn()


def read_product_image(
    product: dict,
    settings: Settings,
    minio_client: Minio | None = None,
) -> Image.Image:
    image_key = product.get("image_key") or product.get("minio_key") or product.get("object_key")
    if image_key:
        client = minio_client or build_minio_client(settings)
        return read_minio_image(client, settings.minio_bucket, image_key)

    image_url = product.get("image_url") or product.get("url") or product.get("image")
    if image_url:
        return read_url_image(image_url, settings.request_timeout_seconds)

    raise ValueError("product has neither image_key nor image_url")
