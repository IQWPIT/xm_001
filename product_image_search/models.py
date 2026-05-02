from typing import Any

from pydantic import BaseModel


class ProductPayload(BaseModel):
    sku_id: str
    site: str | None = None
    category_id: str
    object_name: str | None = None
    active_price: float | None = None
    total_order: int | None = None
    image_url: str | None = None
    image_key: str | None = None


class SearchProduct(BaseModel):
    sku_id: str
    score: float
    best_image: ProductPayload
    product: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    category_id: str | None = None
    global_search: bool = False
    score_threshold: float | None = None
    image_hits: int
    products: list[SearchProduct]
