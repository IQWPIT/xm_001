from __future__ import annotations

from PIL import Image

from product_image_search.config import get_settings
from product_image_search.embedder import DinoV2Embedder
from product_image_search.image_io import build_minio_client, ensure_minio_bucket
from product_image_search.models import ProductPayload, SearchProduct, SearchResponse
from product_image_search.mongo_store import MongoProductStore
from product_image_search.qdrant_store import QdrantImageStore


class ImageSearchService:
    def __init__(self):
        settings = get_settings()
        self.embedder = DinoV2Embedder(settings)
        self.qdrant = QdrantImageStore(settings)
        self.qdrant.ensure_collection(self.embedder.vector_size)
        self.mongo = MongoProductStore(settings)
        self.mongo.ensure_indexes()
        ensure_minio_bucket(build_minio_client(settings), settings.minio_bucket)

    def search(
        self,
        image: Image.Image,
        category_id: str | None = None,
        image_limit: int = 100,
        product_limit: int = 20,
        score_threshold: float | None = None,
        query_image_url: str | None = None,
    ) -> SearchResponse:
        vector = self.embedder.encode([image])[0].tolist()
        hits = self.qdrant.search(
            vector,
            category_id=category_id,
            limit=image_limit,
            score_threshold=score_threshold,
        )

        best_by_sku: dict[str, tuple[float, ProductPayload]] = {}
        if query_image_url:
            for product in self.mongo.find_products_by_image_url(query_image_url, category_id=category_id):
                payload = payload_from_product(product)
                best_by_sku[payload.sku_id] = (1.0, payload)

        for hit in hits:
            if score_threshold is not None and hit.score < score_threshold:
                continue
            payload = ProductPayload.model_validate(hit.payload)
            current = best_by_sku.get(payload.sku_id)
            if current is None or hit.score > current[0]:
                best_by_sku[payload.sku_id] = (float(hit.score), payload)

        ranked = sorted(best_by_sku.items(), key=lambda item: item[1][0], reverse=True)
        ranked = ranked[:product_limit]
        sku_ids = [sku_id for sku_id, _ in ranked]
        products = self.mongo.get_products_by_sku(sku_ids)

        return SearchResponse(
            category_id=category_id,
            global_search=category_id is None,
            score_threshold=score_threshold,
            image_hits=len(hits),
            products=[
                SearchProduct(
                    sku_id=sku_id,
                    score=score,
                    best_image=payload,
                    product=products.get(sku_id),
                )
                for sku_id, (score, payload) in ranked
            ],
        )


def payload_from_product(product: dict) -> ProductPayload:
    return ProductPayload(
        sku_id=str(product["sku_id"]),
        site=product.get("site"),
        category_id=str(product["category_id"]),
        object_name=product.get("object_name"),
        active_price=product.get("active_price"),
        total_order=product.get("total_order"),
        image_url=product.get("image_url") or product.get("url") or product.get("image") or product.get("pic_url"),
        image_key=product.get("image_key") or product.get("minio_key") or product.get("object_key"),
    )
