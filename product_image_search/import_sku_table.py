from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Iterable
from typing import Any

from pymongo import MongoClient, UpdateOne
from tqdm import tqdm

from product_image_search.config import get_settings
from product_image_search.mongo_store import MongoProductStore

logger = logging.getLogger(__name__)


def get_source_sku_collection(site: str, dm_path: str | None = None):
    os.environ.setdefault("NET", "TUNNEL")
    os.environ.setdefault("NET3", "NXQ")

    if dm_path:
        import sys

        if dm_path not in sys.path:
            sys.path.insert(0, dm_path)

    from dm.connector.mongo.manager3 import get_collection

    return get_collection(f"main_{site}", site, "sku")


def get_direct_mongo_collection(uri: str, db: str, collection: str):
    return MongoClient(uri)[db][collection]


def normalize_pic_url(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for item in value:
            normalized = normalize_pic_url(item)
            if normalized:
                return normalized
    if isinstance(value, dict):
        for key in ["url", "pic_url", "secure_url"]:
            normalized = normalize_pic_url(value.get(key))
            if normalized:
                return normalized
    return None


def iter_source_docs(source_collection, category_id: str | None, limit: int | None) -> Iterable[dict]:
    query: dict[str, Any] = {
        "sku_id": {"$exists": True, "$nin": [None, ""]},
        "category_id": {"$exists": True, "$nin": [None, ""]},
        "pic_url": {"$exists": True},
    }
    if category_id:
        query["category_id"] = category_id

    cursor = source_collection.find(
        query,
        {
            "_id": 0,
            "sku_id": 1,
            "category_id": 1,
            "pic_url": 1,
            "object_name": 1,
            "title": 1,
            "active_price": 1,
            "total_order": 1,
            "brand": 1,
        },
    )
    if limit:
        cursor = cursor.limit(limit)
    yield from cursor


def to_product_doc(source_doc: dict, site: str) -> dict | None:
    image_url = normalize_pic_url(source_doc.get("pic_url"))
    if not image_url:
        return None

    sku_id = str(source_doc["sku_id"])
    category_id = str(source_doc["category_id"])
    return {
        "sku_id": sku_id,
        "site": site,
        "category_id": category_id,
        "object_name": source_doc.get("object_name") or source_doc.get("title") or sku_id,
        "active_price": source_doc.get("active_price"),
        "total_order": source_doc.get("total_order"),
        "brand": source_doc.get("brand"),
        "image_url": image_url,
        "pic_url": source_doc.get("pic_url"),
        "source": "sku_table",
        "status": "active",
    }


def run(
    site: str,
    category_id: str | None,
    limit: int | None,
    batch_size: int,
    dm_path: str | None = None,
    source_mongo_uri: str | None = None,
    source_db: str | None = None,
    source_collection_name: str = "sku",
) -> None:
    if source_mongo_uri:
        source_collection = get_direct_mongo_collection(
            source_mongo_uri,
            source_db or site,
            source_collection_name,
        )
    else:
        try:
            source_collection = get_source_sku_collection(site, dm_path=dm_path)
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Cannot import dm.connector.mongo.manager3. Run this in the environment where "
                "product_image_search\\2.py works, pass --dm-path, or use --source-mongo-uri."
            ) from exc

    settings = get_settings()
    mongo = MongoProductStore(settings)
    mongo.ensure_indexes()

    operations: list[UpdateOne] = []
    imported = 0
    skipped = 0

    for source_doc in tqdm(
        iter_source_docs(source_collection, category_id=category_id, limit=limit),
        desc="importing sku table",
    ):
        product_doc = to_product_doc(source_doc, site=site)
        if product_doc is None:
            skipped += 1
            continue

        operations.append(
            UpdateOne(
                {"sku_id": product_doc["sku_id"], "site": site},
                {"$set": product_doc},
                upsert=True,
            )
        )
        if len(operations) >= batch_size:
            result = mongo.collection.bulk_write(operations, ordered=False)
            imported += result.upserted_count + result.modified_count + result.matched_count
            operations.clear()

    if operations:
        result = mongo.collection.bulk_write(operations, ordered=False)
        imported += result.upserted_count + result.modified_count + result.matched_count

    logger.info("done site=%s imported_or_matched=%s skipped=%s", site, imported, skipped)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import sku table rows into local Mongo products.")
    parser.add_argument("--site", default="ml_mx")
    parser.add_argument("--category-id")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dm-path", help="Optional folder to add to sys.path before importing dm.")
    parser.add_argument("--source-mongo-uri", help="Read sku directly from this Mongo URI instead of dm connector.")
    parser.add_argument("--source-db", help="Source Mongo database name. Defaults to --site.")
    parser.add_argument("--source-collection", default="sku")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(
        site=args.site,
        category_id=args.category_id,
        limit=args.limit,
        batch_size=args.batch_size,
        dm_path=args.dm_path,
        source_mongo_uri=args.source_mongo_uri,
        source_db=args.source_db,
        source_collection_name=args.source_collection,
    )


if __name__ == "__main__":
    main()
