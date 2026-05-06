# Product Image Search Project Notes

This document is the operating manual for `D:\https\001`. Read it first when returning to this project.

## Purpose

Build a local product image similarity search system:

```text
Mongo product records
  -> read image from MinIO or URL
  -> RGB + model preprocessing + bad image skip
  -> DINOv2-small 384-dimensional feature
  -> L2 normalize
  -> Qdrant vector upsert
  -> search by uploaded image with category_id filter
  -> top100 image hits
  -> group by sku_id, keep best score
  -> fill product details from Mongo
  -> return top20 similar products
```

## Local Services

Defined in `docker-compose.yml`:

- MongoDB: `localhost:27017`
- MinIO: `localhost:9000`, console `localhost:9001`
- Qdrant: `127.0.0.1:6333`

Use `127.0.0.1` for Qdrant. On this machine, `localhost` can be affected by proxy settings. The code also sets `NO_PROXY` for local Qdrant URLs.

Start services:

```powershell
docker compose up -d
docker compose ps
```

## Python Runtime

The system Python command was not available in PATH during setup. The tested runtime is:

```text
C:\Users\cc\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
```

Dependencies were installed into that runtime, including `torch`, `transformers`, `qdrant-client`, `minio`, `pymongo`, `fastapi`, and `dm`.

`dm` was installed from the private Gitee repository provided by the user. Do not write the credential into docs or logs.

## Configuration

Defaults are in `.env.example` and `product_image_search/config.py`.

Important values:

```text
MONGO_URI=mongodb://localhost:27017
MONGO_DB=product_search
MONGO_COLLECTION=products
MINIO_BUCKET=product-images
QDRANT_URL=http://127.0.0.1:6333
QDRANT_COLLECTION=product_image_vectors
MODEL_NAME=facebook/dinov2-small
```

For repeat runs after the model is cached:

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:QDRANT_URL='http://127.0.0.1:6333'
$env:NO_PROXY='localhost,127.0.0.1,::1'
$env:no_proxy='localhost,127.0.0.1,::1'
```

## Code Map

- `product_image_search/api.py`: FastAPI app, `/health` and `/search`
- `product_image_search/desktop_app.py`: local Tkinter software version for image search and batch category import through the same API
- `product_image_search/static/index.html`: browser UI for upload/URL image search
- `product_image_search/bootstrap.py`: creates local Mongo indexes, MinIO bucket, Qdrant collection
- `product_image_search/config.py`: environment-backed settings
- `product_image_search/embedder.py`: DINOv2-small image embedding, 384 dimensions, L2 normalized
- `product_image_search/image_io.py`: read images from MinIO, URL, or upload bytes
- `product_image_search/import_local_images.py`: import a local image folder into MinIO and local Mongo
- `product_image_search/import_jobs.py`: in-process background job manager for category import from the web UI
- `product_image_search/import_sku_table.py`: import `sku_id/category_id/pic_url` from the remote SKU table through `dm`
- `product_image_search/index_products.py`: read local Mongo products, extract features, upsert Qdrant
- `product_image_search/mongo_store.py`: local Mongo access and indexes
- `product_image_search/qdrant_store.py`: Qdrant collection, payload indexes, search, existing SKU scan
- `product_image_search/search_service.py`: query image -> Qdrant -> group by SKU -> Mongo details
- `product_image_search/subject_crop.py`: query-time subject crop used by subject search to reduce background influence
- `product_image_search/2.py`: user-provided minimal example for accessing the SKU table through `dm`

## Data Model

Local Mongo product document shape:

```json
{
  "sku_id": "SKU001",
  "site": "ml_mx",
  "category_id": "MLM194295",
  "object_name": "product title or sku_id",
  "active_price": 99.9,
  "total_order": 10,
  "brand": "optional",
  "image_url": "https://...",
  "image_key": "optional/minio/object.webp",
  "pic_url": "original SKU table value",
  "source": "sku_table",
  "status": "active"
}
```

Image read priority:

1. `image_key`, `minio_key`, or `object_key` from MinIO
2. `image_url`, `url`, or `image` from HTTP(S)

Qdrant payload:

```json
{
  "sku_id": "SKU001",
  "site": "ml_mx",
  "category_id": "MLM194295",
  "object_name": "name",
  "active_price": 99.9,
  "total_order": 10,
  "image_url": "https://...",
  "image_key": "optional/minio/object.webp"
}
```

Qdrant point IDs are stable UUIDv5 values. Qdrant does not accept arbitrary SHA1 strings as point IDs.

## Current Imported Data

Known local test data:

- `TEST_COSMETICS`: local image tests from `D:\https\001\datas` plus earlier SACE LADY test data
- `ml_mx`, category `MLM194295`: imported from SKU table

Latest confirmed counts for `MLM194295`:

```text
Mongo products: 2348
Qdrant vectors: 2347
Skipped images: 1
```

The import command saw 2363 SKU rows, wrote or matched 2348 local Mongo records, and skipped 15 rows without usable picture URLs. Vector indexing skipped 1 unreadable or failed image.

## Common Commands

Bootstrap local resources:

```powershell
python -m product_image_search.bootstrap
```

Import local folder images:

```powershell
python -m product_image_search.import_local_images D:\https\001\datas --category-id TEST_COSMETICS --site local_datas
```

Import SKU table data through `dm`:

```powershell
python -m product_image_search.import_sku_table --site ml_mx --category-id MLM194295 --batch-size 500
```

Build or resume vector index:

```powershell
python -m product_image_search.index_products --site ml_mx --category-id MLM194295 --batch-size 32 --skip-existing
```

Run API:

```powershell
uvicorn product_image_search.api:app --host 127.0.0.1 --port 8000
```

Open the search UI:

```text
http://127.0.0.1:8000/
```

The UI also has a separate `数据导入` view for category import. Enter one or more category IDs, such as `MLM2789`, separated by newlines, commas, spaces, or semicolons, and click import. The backend queues one job per category and runs SKU import and then vector indexing with `skip_existing=true`.

Batch import API:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/import-categories?category_ids=MLM2789,MLM194295&site=ml_mx&skip_existing=true"
```

Run the local software version:

```powershell
python -m product_image_search.desktop_app
```

Or double-click:

```text
D:\https\001\start_desktop_app.cmd
```

API form:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/import-category?category_id=MLM2789&site=ml_mx"
```

Poll job status:

```powershell
curl.exe "http://127.0.0.1:8000/import-category/<job_id>"
```

Cancel a web import job:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/import-category/<job_id>/cancel"
```

Stop standalone index processes for a category:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/stop-category?category_id=MLM2789&site=ml_mx"
```

Search with an image:

```powershell
curl.exe -F "file=@C:\path\query.webp" "http://127.0.0.1:8000/search?category_id=MLM194295"
```

Search with an image URL:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/search-url?category_id=MLM194295&url=https%3A%2F%2Fhttp2.mlstatic.com%2FD_NQ_NP_873813-MLM86754197062_072025-V.webp"
```

Global search ignores category filtering and returns only products above `score_threshold`:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/search-url?global_search=true&score_threshold=0.8&product_limit=20&url=https%3A%2F%2Fhttp2.mlstatic.com%2FD_NQ_NP_873813-MLM86754197062_072025-V.webp"
```

Subject search crops the likely product subject before embedding the query image:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/search-url?category_id=MLM2789&subject_search=true&url=https%3A%2F%2Fhttp2.mlstatic.com%2Fexample.webp"
```

## Verification Snippets

Count local Mongo category records:

```powershell
@'
from pymongo import MongoClient
coll = MongoClient('mongodb://localhost:27017')['product_search']['products']
print(coll.count_documents({'site': 'ml_mx', 'category_id': 'MLM194295'}))
'@ | python -
```

Count Qdrant vectors by category:

```powershell
@'
from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue
client = QdrantClient(url='http://127.0.0.1:6333', check_compatibility=False)
flt = Filter(must=[FieldCondition(key='category_id', match=MatchValue(value='MLM194295'))])
print(client.count(collection_name='product_image_vectors', count_filter=flt, exact=True).count)
'@ | python -
```

## Known Issues And Decisions

- URL image indexing is slow because every SKU image is downloaded remotely during indexing.
- `--skip-existing` was added to resume long indexing jobs without reprocessing SKU IDs already present in Qdrant.
- Batch category import deduplicates at the SKU level. Mongo writes use `sku_id + site` upserts, and Qdrant `skip_existing` checks existing SKU IDs globally for the site rather than only inside the same category.
- Batch import status can be read with `/import-categories-status?job_ids=<id1,id2>`, and a whole submitted batch can be cancelled with `/import-categories-cancel?job_ids=<id1,id2>`.
- Import job management is hardened: the worker pool uses two workers so one stuck import does not block all queued jobs, duplicate queued/running jobs for the same `site + category_id` are reused, `/import-jobs` lists current in-memory jobs, and `/import-jobs/clear-finished` clears completed/failed/cancelled jobs.
- `localhost` to Qdrant can time out or return 502 if proxy variables intercept it. Prefer `127.0.0.1`.
- DINOv2-small uses whole-image features. Ad-style images, text-heavy images, and different layouts can lower similarity even for related products.
- Searching with an image already in the index returns itself as top1. Future API work should add `exclude_sku_id` or `exclude_image_key`.
- The browser UI loads categories from local Mongo and supports file upload, image URL search, category mode, and global search with `score_threshold`.
- URL image search first checks local Mongo for an exact `image_url`/`pic_url` match. If the query URL already belongs to an indexed product, that SKU is forced into the result set with score `1.0`, so products can reliably search back to themselves.
- Search supports `subject_search=true` from the browser UI, desktop app, and API. It crops the query image's likely foreground subject before DINOv2 embedding, which reduces background, text, and ad-layout influence. Indexed product vectors remain unchanged.
- The browser UI text is Chinese. Keep the HTML file encoded as UTF-8 when editing.
- Category import can be launched from the browser UI under the separate `数据导入` view, keeping the main search controls focused on image search. It supports single or batch category input. It runs inside the FastAPI process with one background worker. Long jobs continue while the page polls status, but will stop if the API process is restarted.
- The browser and desktop import UIs show a per-category batch task table with category, stage, and live `Mongo / Qdrant` counts. Batch cancel requests cancel every submitted job ID; queued jobs now stop before starting.
- The browser and desktop import UIs include a refresh task action that reads `/import-jobs`, so users can recover from stale browser/local state and see the actual backend queue.
- Category import status shows Mongo count after SKU import and Qdrant count when entering indexing, then refreshes final counts when the job completes. Existing running jobs use the code version that was loaded when the API process started.
- The web UI stores the latest import job in browser `localStorage`, restores polling after page refresh, and falls back to `/category-status` counts if the in-memory job is gone.
- The web UI has a stop button. It cancels the in-process import job when possible and terminates standalone `index_products` processes matching the category ID.
- During category indexing, the background job updates indexed/skipped counts after each vector batch and refreshes Qdrant counts while the UI polls status. If an old browser `job_id` is missing after an API restart, the UI tries to reconnect to `/import-category-latest`; otherwise it switches to polling `/category-status` so Qdrant totals continue to move during standalone indexing without showing a stale job error.
- The import UI keeps a stable status area and shows live counts such as `Mongo 6358 / Qdrant 970`. It does not use a progress bar.
- Import job status endpoints enrich queued, running, cancelled, and cancel-requested jobs with live Mongo/Qdrant counts before returning, so the UI does not show `Mongo - / Qdrant -` when counts are available.
- The import UI also has a front-end fallback: if a job response still has missing counts, it immediately reads `/category-status` for that category and updates the live count line.
- Empty import counts are displayed as `-` instead of `0`, so queued/importing jobs do not look like real zero-progress data before counts are known.
- On 2026-04-30, local Mongo products without `category_id` were checked for cleanup; count was 0, so no records were deleted.

## Maintenance Rule

Whenever the project changes, update this document in the same turn.

Update `PROJECT.md` when changing:

- data source or import behavior
- Mongo/Qdrant/MinIO schemas or collection names
- model name, vector size, preprocessing, or similarity settings
- operational commands
- imported category status or counts
- known issues, fixes, or environment requirements

Keep `README.md` as the short quick-start guide. Keep `PROJECT.md` as the detailed project memory.
