from __future__ import annotations

from typing import Any

from pymongo import MongoClient
from pymongo import ASCENDING

from product_image_search.config import Settings


class MongoProductStore:
    def __init__(self, settings: Settings):
        self.client = MongoClient(settings.mongo_uri)
        self.collection = self.client[settings.mongo_db][settings.mongo_collection]

    def ensure_indexes(self) -> None:
        self.collection.create_index([("sku_id", ASCENDING)], name="sku_id_idx")
        self.collection.create_index([("category_id", ASCENDING)], name="category_id_idx")
        self.collection.create_index([("site", ASCENDING)], name="site_idx")
        self.collection.create_index([("image_url", ASCENDING)], name="image_url_idx")
        self.collection.create_index([("pic_url", ASCENDING)], name="pic_url_idx")
        self.collection.create_index(
            [("category_id", ASCENDING), ("site", ASCENDING)],
            name="category_site_idx",
        )

    def iter_products(
        self,
        site: str | None = None,
        category_id: str | None = None,
        limit: int | None = None,
    ):
        query: dict[str, Any] = {}
        if site:
            query["site"] = site
        if category_id:
            query["category_id"] = category_id

        cursor = self.collection.find(query)
        if limit:
            cursor = cursor.limit(limit)
        yield from cursor

    def get_products_by_sku(self, sku_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not sku_ids:
            return {}

        docs = self.collection.find({"sku_id": {"$in": sku_ids}})
        products: dict[str, dict[str, Any]] = {}
        for doc in docs:
            doc["_id"] = str(doc["_id"])
            products[str(doc["sku_id"])] = doc
        return products

    def find_products_by_image_url(
        self,
        image_url: str,
        category_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {
            "$or": [
                {"image_url": image_url},
                {"pic_url": image_url},
                {"url": image_url},
                {"image": image_url},
            ]
        }
        if category_id:
            query["category_id"] = category_id

        docs = []
        for doc in self.collection.find(query):
            doc["_id"] = str(doc["_id"])
            docs.append(doc)
        return docs
