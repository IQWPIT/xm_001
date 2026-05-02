from __future__ import annotations

import argparse
import logging

from tqdm import tqdm

from product_image_search.config import get_settings
from product_image_search.embedder import DinoV2Embedder
from product_image_search.image_io import build_minio_client, ensure_minio_bucket, read_product_image
from product_image_search.models import ProductPayload
from product_image_search.mongo_store import MongoProductStore
from product_image_search.qdrant_store import QdrantImageStore

logger = logging.getLogger(__name__)


def to_payload(product: dict) -> ProductPayload:
    return ProductPayload(
        sku_id=str(product["sku_id"]),
        site=product.get("site"),
        category_id=str(product["category_id"]),
        object_name=product.get("object_name"),
        active_price=product.get("active_price"),
        total_order=product.get("total_order"),
        image_url=product.get("image_url") or product.get("url") or product.get("image"),
        image_key=product.get("image_key") or product.get("minio_key") or product.get("object_key"),
    )


def flush_batch(embedder, qdrant, images, payloads) -> int:
    if not images:
        return 0
    vectors = embedder.encode(images)
    qdrant.upsert((vector.tolist(), payload) for vector, payload in zip(vectors, payloads, strict=True))
    return len(images)


def run(
    site: str | None,
    category_id: str | None,
    limit: int | None,
    batch_size: int,
    skip_existing: bool = False,
    should_stop=None,
    progress_callback=None,
    dedupe_by_sku: bool = True,
) -> None:
    settings = get_settings()
    mongo = MongoProductStore(settings)
    minio_client = build_minio_client(settings)
    mongo.ensure_indexes()
    ensure_minio_bucket(minio_client, settings.minio_bucket)
    embedder = DinoV2Embedder(settings)
    qdrant = QdrantImageStore(settings)
    qdrant.ensure_collection(embedder.vector_size)
    existing_sku_ids = set()
    if skip_existing:
        existing_category_id = None if dedupe_by_sku else category_id
        existing_sku_ids = qdrant.existing_sku_ids(category_id=existing_category_id, site=site)
        logger.info("skip_existing enabled: found %s existing sku_ids", len(existing_sku_ids))

    images = []
    payloads = []
    indexed = 0
    skipped = 0

    def flush_pending() -> int:
        flushed = flush_batch(embedder, qdrant, images, payloads)
        if flushed:
            images.clear()
            payloads.clear()
            if progress_callback is not None:
                progress_callback(indexed=indexed + flushed, skipped=skipped)
        return flushed

    products = mongo.iter_products(site=site, category_id=category_id, limit=limit)
    for product in tqdm(products, desc="indexing products"):
        if should_stop is not None and should_stop():
            indexed += flush_pending()
            raise InterruptedError("indexing cancelled")
        if str(product.get("sku_id")) in existing_sku_ids:
            continue
        try:
            payload = to_payload(product)
            image = read_product_image(product, settings, minio_client)
        except Exception as exc:
            skipped += 1
            logger.warning("skip product sku_id=%s: %s", product.get("sku_id"), exc)
            continue

        images.append(image)
        payloads.append(payload)
        if len(images) >= batch_size:
            if should_stop is not None and should_stop():
                indexed += flush_pending()
                raise InterruptedError("indexing cancelled")
            indexed += flush_pending()

    indexed += flush_pending()
    logger.info("done indexed=%s skipped=%s", indexed, skipped)


def main() -> None:
    parser = argparse.ArgumentParser(description="Index product images into Qdrant.")
    parser.add_argument("--site")
    parser.add_argument("--category-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    run(
        site=args.site,
        category_id=args.category_id,
        limit=args.limit,
        batch_size=args.batch_size or settings.batch_size,
        skip_existing=args.skip_existing,
    )


if __name__ == "__main__":
    main()
