# Product Image Similarity Search

Read `PROJECT.md` first for the full project operating notes, current data status, and maintenance rules.

This project creates and uses local storage only:

- Product data: local MongoDB
- Product images: local MinIO, or remote URL fallback
- Vector index: local Qdrant
- Feature model: `facebook/dinov2-small`, 384 dimensions
- Retrieval: HNSW in Qdrant with `category_id` payload filtering

Pipeline:

```text
Mongo products
  -> MinIO / URL image read
  -> RGB + model preprocessing + bad image skip
  -> DINOv2-small 384-d feature
  -> L2 normalize
  -> Qdrant upsert
```

Query:

```text
Upload image
  -> same preprocessing
  -> DINOv2-small feature
  -> Qdrant search with category_id filter
  -> top100 image hits
  -> group by sku_id, keep best score
  -> Mongo product detail fill
  -> top20 similar products
```

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
docker compose up -d
```

Create local resources:

```powershell
python -m product_image_search.bootstrap
```

The bootstrap command creates:

- MongoDB database and collection on first write, plus indexes for `sku_id`, `category_id`, `site`
- MinIO bucket from `MINIO_BUCKET`
- Qdrant collection from `QDRANT_COLLECTION`, with HNSW and payload indexes

## Product Documents

The indexer reads `.env` values `MONGO_DB` and `MONGO_COLLECTION`.

Each product should contain:

```json
{
  "sku_id": "SKU001",
  "site": "ml_br",
  "category_id": "MLB1234",
  "object_name": "camera",
  "active_price": 199.9,
  "total_order": 32,
  "image_url": "https://...",
  "image_key": "optional/minio/object.jpg",
  "status": "active"
}
```

Image priority:

1. `image_key`, `minio_key`, or `object_key` from MinIO bucket
2. `image_url`, `url`, or `image` from HTTP(S)

## Build Vector Index

Import local images into MinIO and Mongo:

```powershell
python -m product_image_search.import_local_images D:\https\001\datas --category-id TEST_COSMETICS
```

Import products from the remote sku table used by `product_image_search\2.py`:

```powershell
python -m product_image_search.import_sku_table --site ml_mx --limit 1000
```

If the `dm` connector is not available in the current Python environment, import from a direct Mongo URI:

```powershell
python -m product_image_search.import_sku_table --site ml_mx --source-mongo-uri mongodb://host:27017 --source-db ml_mx --source-collection sku --limit 1000
```

Then build vectors from `pic_url`:

```powershell
python -m product_image_search.index_products --site ml_mx --limit 1000
```

```powershell
python -m product_image_search.index_products --limit 1000
```

Useful filters:

```powershell
python -m product_image_search.index_products --site ml_br --category-id MLB1234 --batch-size 32
```

## Search API

```powershell
uvicorn product_image_search.api:app --host 0.0.0.0 --port 8000
```

Open the browser UI:

```text
http://127.0.0.1:8000/
```

```powershell
curl -F "file=@query.jpg" "http://localhost:8000/search?category_id=MLB1234"
```

Global search without category filtering:

```powershell
curl -X POST "http://127.0.0.1:8000/search-url?global_search=true&score_threshold=0.8&url=https%3A%2F%2Fexample.com%2Fquery.webp"
```

The API returns top20 products. Each product is the best image match for that `sku_id`, with details filled from MongoDB.
