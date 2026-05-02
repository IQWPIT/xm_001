from __future__ import annotations

import uuid
from collections.abc import Iterable
import os
from urllib.parse import urlparse

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    PointStruct,
    VectorParams,
)

from product_image_search.config import Settings
from product_image_search.models import ProductPayload


class QdrantImageStore:
    def __init__(self, settings: Settings):
        self.collection_name = settings.qdrant_collection
        ensure_no_proxy_for_local_url(settings.qdrant_url)
        self.client = QdrantClient(url=settings.qdrant_url, check_compatibility=False)

    def ensure_collection(self, vector_size: int) -> None:
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                hnsw_config=HnswConfigDiff(m=16, ef_construct=128),
            )
        self.ensure_payload_indexes()

    def ensure_payload_indexes(self) -> None:
        for field_name in ["category_id", "sku_id", "site"]:
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name=field_name,
                field_schema="keyword",
            )

    def upsert(self, rows: Iterable[tuple[list[float], ProductPayload]]) -> None:
        points = [
            PointStruct(
                id=stable_point_id(payload),
                vector=vector,
                payload=payload.model_dump(exclude_none=True),
            )
            for vector, payload in rows
        ]
        if points:
            self.client.upsert(collection_name=self.collection_name, points=points)

    def search(
        self,
        vector: list[float],
        category_id: str | None = None,
        limit: int = 100,
        score_threshold: float | None = None,
    ):
        query_filter = None
        if category_id:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="category_id",
                        match=MatchValue(value=category_id),
                    )
                ]
            )
        return self.client.search(
            collection_name=self.collection_name,
            query_vector=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            score_threshold=score_threshold,
        )

    def existing_sku_ids(self, category_id: str | None = None, site: str | None = None) -> set[str]:
        must = []
        if category_id:
            must.append(
                FieldCondition(
                    key="category_id",
                    match=MatchValue(value=category_id),
                )
            )
        if site:
            must.append(FieldCondition(key="site", match=MatchValue(value=site)))

        found: set[str] = set()
        next_page = None
        while True:
            points, next_page = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(must=must) if must else None,
                limit=1000,
                offset=next_page,
                with_payload=["sku_id"],
                with_vectors=False,
            )
            for point in points:
                sku_id = (point.payload or {}).get("sku_id")
                if sku_id:
                    found.add(str(sku_id))
            if next_page is None:
                return found


def stable_point_id(payload: ProductPayload) -> str:
    raw = "|".join(
        [
            payload.site or "",
            payload.category_id,
            payload.sku_id,
            payload.image_key or payload.image_url or "",
        ]
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def ensure_no_proxy_for_local_url(url: str) -> None:
    hostname = urlparse(url).hostname
    if hostname not in {"localhost", "127.0.0.1", "::1"}:
        return

    needed = ["localhost", "127.0.0.1", "::1"]
    for env_name in ["NO_PROXY", "no_proxy"]:
        current = os.environ.get(env_name, "")
        parts = [part.strip() for part in current.split(",") if part.strip()]
        for item in needed:
            if item not in parts:
                parts.append(item)
        os.environ[env_name] = ",".join(parts)
