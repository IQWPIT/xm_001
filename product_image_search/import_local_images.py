from __future__ import annotations

import argparse
import logging
from pathlib import Path

from minio import Minio

from product_image_search.config import get_settings
from product_image_search.image_io import build_minio_client, ensure_minio_bucket
from product_image_search.mongo_store import MongoProductStore

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def iter_images(folder: Path):
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".bmp":
        return "image/bmp"
    return "application/octet-stream"


def upload_image(client: Minio, bucket: str, path: Path, object_prefix: str) -> str:
    object_name = f"{object_prefix.strip('/')}/{path.name}"
    client.fput_object(bucket, object_name, str(path), content_type=content_type_for(path))
    return object_name


def run(folder: Path, category_id: str, site: str, object_prefix: str, replace: bool) -> None:
    if not folder.exists() or not folder.is_dir():
        raise ValueError(f"folder does not exist: {folder}")

    settings = get_settings()
    minio_client = build_minio_client(settings)
    ensure_minio_bucket(minio_client, settings.minio_bucket)

    mongo = MongoProductStore(settings)
    mongo.ensure_indexes()

    imported = 0
    for image_path in iter_images(folder):
        sku_id = image_path.stem
        image_key = upload_image(minio_client, settings.minio_bucket, image_path, object_prefix)
        doc = {
            "sku_id": sku_id,
            "site": site,
            "category_id": category_id,
            "object_name": image_path.stem,
            "active_price": None,
            "total_order": None,
            "image_key": image_key,
            "source_path": str(image_path),
            "status": "active",
        }
        if replace:
            mongo.collection.replace_one({"sku_id": sku_id, "site": site}, doc, upsert=True)
        else:
            mongo.collection.update_one(
                {"sku_id": sku_id, "site": site},
                {"$setOnInsert": doc},
                upsert=True,
            )
        imported += 1
        logger.info("imported sku_id=%s image_key=%s", sku_id, image_key)

    logger.info("done imported=%s folder=%s category_id=%s", imported, folder, category_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import local image files into MinIO and Mongo.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--category-id", default="TEST_COSMETICS")
    parser.add_argument("--site", default="local_datas")
    parser.add_argument("--object-prefix", default="datas")
    parser.add_argument("--no-replace", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(
        folder=args.folder,
        category_id=args.category_id,
        site=args.site,
        object_prefix=args.object_prefix,
        replace=not args.no_replace,
    )


if __name__ == "__main__":
    main()
