from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from product_image_search.config import get_settings
from product_image_search.image_io import open_rgb_image, read_url_image
from product_image_search.import_jobs import count_mongo_products, safe_count_qdrant_vectors
from product_image_search.import_jobs import manager as import_job_manager
from product_image_search.import_jobs import stop_index_processes
from product_image_search.models import SearchResponse
from product_image_search.mongo_store import MongoProductStore
from product_image_search.search_service import ImageSearchService

app = FastAPI(title="Product Image Similarity Search")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@lru_cache
def get_service() -> ImageSearchService:
    return ImageSearchService()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/categories")
def categories():
    settings = get_settings()
    store = MongoProductStore(settings)
    values = store.collection.distinct("category_id", {"category_id": {"$exists": True, "$nin": [None, ""]}})
    return {"categories": sorted(str(value) for value in values)}


@app.post("/import-category")
def import_category(
    category_id: str = Query(..., min_length=1),
    site: str = Query(default="ml_mx"),
    limit: int | None = Query(default=None, ge=1),
    import_batch_size: int = Query(default=500, ge=1, le=5000),
    index_batch_size: int = Query(default=32, ge=1, le=256),
    skip_existing: bool = Query(default=True),
):
    return import_job_manager.start(
        category_id=category_id.strip(),
        site=site.strip(),
        import_batch_size=import_batch_size,
        index_batch_size=index_batch_size,
        limit=limit,
        skip_existing=skip_existing,
    )


@app.post("/import-categories")
def import_categories(
    category_ids: str = Query(..., min_length=1),
    site: str = Query(default="ml_mx"),
    limit: int | None = Query(default=None, ge=1),
    import_batch_size: int = Query(default=500, ge=1, le=5000),
    index_batch_size: int = Query(default=32, ge=1, le=256),
    skip_existing: bool = Query(default=True),
):
    categories = [item.strip() for item in re.split(r"[\s,，;；]+", category_ids) if item.strip()]
    jobs = import_job_manager.start_batch(
        category_ids=categories,
        site=site.strip(),
        import_batch_size=import_batch_size,
        index_batch_size=index_batch_size,
        limit=limit,
        skip_existing=skip_existing,
    )
    return {
        "site": site.strip(),
        "category_ids": [job["category_id"] for job in jobs],
        "job_count": len(jobs),
        "dedupe_key": "sku_id",
        "jobs": jobs,
    }


@app.get("/import-category/{job_id}")
def import_category_status(job_id: str):
    job = import_job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.post("/import-category/{job_id}/cancel")
def import_category_cancel(job_id: str):
    job = import_job_manager.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.post("/stop-category")
def stop_category(
    category_id: str = Query(..., min_length=1),
    site: str = Query(default="ml_mx"),
):
    category_id = category_id.strip()
    site = site.strip()
    stopped = stop_index_processes(category_id=category_id)
    return {
        "category_id": category_id,
        "site": site,
        "stopped_processes": stopped,
        "mongo_count": count_mongo_products(site=site, category_id=category_id),
        "qdrant_count": safe_count_qdrant_vectors(category_id=category_id),
    }


@app.get("/import-category-latest")
def import_category_latest():
    return import_job_manager.latest() or {"status": "empty"}


@app.get("/category-status")
def category_status(
    category_id: str = Query(..., min_length=1),
    site: str = Query(default="ml_mx"),
):
    category_id = category_id.strip()
    site = site.strip()
    return {
        "category_id": category_id,
        "site": site,
        "mongo_count": count_mongo_products(site=site, category_id=category_id),
        "qdrant_count": safe_count_qdrant_vectors(category_id=category_id),
    }


@app.post("/search", response_model=SearchResponse)
async def search(
    file: UploadFile = File(...),
    category_id: str | None = Query(default=None),
    global_search: bool = Query(default=False),
    score_threshold: float | None = Query(default=None, ge=0, le=1),
    image_limit: int = Query(default=100, ge=1, le=500),
    product_limit: int = Query(default=20, ge=1, le=100),
):
    resolved_category_id = None if global_search else category_id
    if not resolved_category_id and not global_search:
        raise HTTPException(status_code=400, detail="category_id is required unless global_search=true")
    image = open_rgb_image(await file.read())
    return get_service().search(
        image=image,
        category_id=resolved_category_id,
        image_limit=image_limit,
        product_limit=product_limit,
        score_threshold=score_threshold,
    )


@app.post("/search-url", response_model=SearchResponse)
async def search_url(
    url: str = Query(...),
    category_id: str | None = Query(default=None),
    global_search: bool = Query(default=False),
    score_threshold: float | None = Query(default=None, ge=0, le=1),
    image_limit: int = Query(default=100, ge=1, le=500),
    product_limit: int = Query(default=20, ge=1, le=100),
):
    resolved_category_id = None if global_search else category_id
    if not resolved_category_id and not global_search:
        raise HTTPException(status_code=400, detail="category_id is required unless global_search=true")
    try:
        image = read_url_image(url, get_settings().request_timeout_seconds)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to read image url: {exc}") from exc
    return get_service().search(
        image=image,
        category_id=resolved_category_id,
        image_limit=image_limit,
        product_limit=product_limit,
        score_threshold=score_threshold,
        query_image_url=url,
    )
