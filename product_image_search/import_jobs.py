from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import psutil
from qdrant_client.http.models import FieldCondition, Filter, MatchValue

from product_image_search.config import get_settings
from product_image_search.import_sku_table import run as import_sku_table_run
from product_image_search.index_products import run as index_products_run
from product_image_search.mongo_store import MongoProductStore
from product_image_search.qdrant_store import QdrantImageStore


class ImportJobManager:
    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    def start(
        self,
        category_id: str,
        site: str = "ml_mx",
        import_batch_size: int = 500,
        index_batch_size: int = 32,
        limit: int | None = None,
        skip_existing: bool = True,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "category_id": category_id,
            "site": site,
            "status": "queued",
            "stage": "queued",
            "message": "Waiting to start.",
            "started_at": now_iso(),
            "finished_at": None,
            "mongo_count": None,
            "qdrant_count": None,
            "error": None,
            "cancel_requested": False,
        }
        cancel_event = threading.Event()
        with self._lock:
            self._jobs[job_id] = job
            self._cancel_events[job_id] = cancel_event
        self._executor.submit(
            self._run_job,
            job_id,
            category_id,
            site,
            import_batch_size,
            index_batch_size,
            limit,
            skip_existing,
            cancel_event,
        )
        return job.copy()

    def start_batch(
        self,
        category_ids: list[str],
        site: str = "ml_mx",
        import_batch_size: int = 500,
        index_batch_size: int = 32,
        limit: int | None = None,
        skip_existing: bool = True,
    ) -> list[dict[str, Any]]:
        jobs = []
        seen: set[str] = set()
        for category_id in category_ids:
            normalized = category_id.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            jobs.append(
                self.start(
                    category_id=normalized,
                    site=site,
                    import_batch_size=import_batch_size,
                    index_batch_size=index_batch_size,
                    limit=limit,
                    skip_existing=skip_existing,
                )
            )
        return jobs

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            snapshot = job.copy() if job else None
        return self._with_live_counts(job_id, snapshot)

    def get_many(self, job_ids: list[str]) -> list[dict[str, Any]]:
        jobs = []
        for job_id in job_ids:
            job = self.get(job_id)
            if job is not None:
                jobs.append(job)
        return jobs

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._jobs:
                return None
            job = next(reversed(self._jobs.values()))
            job_id = job["job_id"]
            snapshot = job.copy()
        return self._with_live_counts(job_id, snapshot)

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            event = self._cancel_events.get(job_id)
            if event is not None:
                event.set()
            updates = {
                "cancel_requested": True,
                "message": "Cancel requested. Waiting for current image operation to stop.",
            }
            if job.get("status") == "queued":
                updates.update(
                    {
                        "status": "cancelled",
                        "stage": "cancelled",
                        "message": "Cancelled before start.",
                        "finished_at": now_iso(),
                    }
                )
            job.update(updates)
            snapshot = job.copy()
        return self._with_live_counts(job_id, snapshot)

    def cancel_many(self, job_ids: list[str]) -> list[dict[str, Any]]:
        jobs = []
        for job_id in job_ids:
            job = self.cancel(job_id)
            if job is not None:
                jobs.append(job)
        return jobs

    def _patch(self, job_id: str, **updates) -> None:
        with self._lock:
            self._jobs[job_id].update(updates)

    def _with_live_counts(self, job_id: str, snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        site = snapshot.get("site") or "ml_mx"
        category_id = snapshot.get("category_id")
        if not category_id:
            return snapshot

        mongo_count = count_mongo_products(site=site, category_id=category_id)
        qdrant_count = safe_count_qdrant_vectors(category_id=category_id)
        updates = {"mongo_count": mongo_count, "qdrant_count": qdrant_count}
        self._patch(job_id, **updates)
        snapshot.update(updates)
        return snapshot

    def _run_job(
        self,
        job_id: str,
        category_id: str,
        site: str,
        import_batch_size: int,
        index_batch_size: int,
        limit: int | None,
        skip_existing: bool,
        cancel_event: threading.Event,
    ) -> None:
        try:
            if cancel_event.is_set():
                self._patch(
                    job_id,
                    status="cancelled",
                    stage="cancelled",
                    message="Cancelled before start.",
                    mongo_count=count_mongo_products(site=site, category_id=category_id),
                    qdrant_count=safe_count_qdrant_vectors(category_id=category_id),
                    finished_at=now_iso(),
                )
                return
            self._patch(
                job_id,
                status="running",
                stage="importing",
                message="Importing SKU rows into local Mongo.",
            )
            import_sku_table_run(
                site=site,
                category_id=category_id,
                limit=limit,
                batch_size=import_batch_size,
            )
            if cancel_event.is_set():
                self._patch(
                    job_id,
                    status="cancelled",
                    stage="cancelled",
                    message="Cancelled after SKU import.",
                    mongo_count=count_mongo_products(site=site, category_id=category_id),
                    qdrant_count=safe_count_qdrant_vectors(category_id=category_id),
                    finished_at=now_iso(),
                )
                return
            mongo_count = count_mongo_products(site=site, category_id=category_id)
            qdrant_base_count = safe_count_qdrant_vectors(category_id=category_id)
            self._patch(
                job_id,
                stage="indexing",
                message=f"Imported Mongo records. Building vectors with skip_existing={skip_existing}.",
                mongo_count=mongo_count,
                qdrant_count=qdrant_base_count,
            )

            def update_index_progress(indexed: int, skipped: int) -> None:
                qdrant_count = None if qdrant_base_count is None else qdrant_base_count + indexed
                self._patch(
                    job_id,
                    message=(
                        f"Building vectors with skip_existing={skip_existing}. "
                        f"Indexed {indexed}, skipped {skipped}."
                    ),
                    qdrant_count=qdrant_count,
                    indexed_count=indexed,
                    skipped_count=skipped,
                )

            index_products_run(
                site=site,
                category_id=category_id,
                limit=limit,
                batch_size=index_batch_size,
                skip_existing=skip_existing,
                should_stop=cancel_event.is_set,
                progress_callback=update_index_progress,
                dedupe_by_sku=True,
            )
            self._patch(
                job_id,
                status="completed",
                stage="done",
                message="Import and vector indexing completed.",
                mongo_count=count_mongo_products(site=site, category_id=category_id),
                qdrant_count=count_qdrant_vectors(category_id=category_id),
                finished_at=now_iso(),
            )
        except InterruptedError as exc:
            self._patch(
                job_id,
                status="cancelled",
                stage="cancelled",
                message=str(exc),
                mongo_count=count_mongo_products(site=site, category_id=category_id),
                qdrant_count=safe_count_qdrant_vectors(category_id=category_id),
                finished_at=now_iso(),
            )
        except Exception as exc:
            self._patch(
                job_id,
                status="failed",
                stage="failed",
                message="Import job failed.",
                error=str(exc),
                mongo_count=count_mongo_products(site=site, category_id=category_id),
                qdrant_count=safe_count_qdrant_vectors(category_id=category_id),
                finished_at=now_iso(),
            )


def count_mongo_products(site: str, category_id: str) -> int:
    store = MongoProductStore(get_settings())
    return store.collection.count_documents({"site": site, "category_id": category_id})


def count_qdrant_vectors(category_id: str) -> int:
    settings = get_settings()
    qdrant = QdrantImageStore(settings)
    flt = Filter(must=[FieldCondition(key="category_id", match=MatchValue(value=category_id))])
    return qdrant.client.count(
        collection_name=settings.qdrant_collection,
        count_filter=flt,
        exact=True,
    ).count


def safe_count_qdrant_vectors(category_id: str) -> int | None:
    try:
        return count_qdrant_vectors(category_id)
    except Exception:
        return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stop_index_processes(category_id: str) -> list[dict[str, Any]]:
    stopped: list[dict[str, Any]] = []
    current_pid = psutil.Process().pid
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["pid"] == current_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            joined = " ".join(cmdline)
            if "product_image_search.index_products" not in joined:
                continue
            if category_id not in joined:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=8)
                stopped.append({"pid": proc.info["pid"], "status": "terminated"})
            except psutil.TimeoutExpired:
                proc.kill()
                stopped.append({"pid": proc.info["pid"], "status": "killed"})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return stopped


manager = ImportJobManager()
