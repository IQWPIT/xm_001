from __future__ import annotations

import argparse
import logging

from product_image_search.config import get_settings
from product_image_search.embedder import DinoV2Embedder
from product_image_search.image_io import build_minio_client, ensure_minio_bucket
from product_image_search.mongo_store import MongoProductStore
from product_image_search.qdrant_store import QdrantImageStore

logger = logging.getLogger(__name__)


def run(load_model: bool = False) -> None:
    settings = get_settings()

    mongo = MongoProductStore(settings)
    mongo.ensure_indexes()
    logger.info(
        "Mongo ready: database=%s collection=%s",
        settings.mongo_db,
        settings.mongo_collection,
    )

    minio_client = build_minio_client(settings)
    ensure_minio_bucket(minio_client, settings.minio_bucket)
    logger.info("MinIO ready: bucket=%s", settings.minio_bucket)

    vector_size = DinoV2Embedder.vector_size
    if load_model:
        vector_size = DinoV2Embedder(settings).vector_size
    qdrant = QdrantImageStore(settings)
    qdrant.ensure_collection(vector_size)
    logger.info("Qdrant ready: collection=%s vector_size=%s", settings.qdrant_collection, vector_size)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create local Mongo, MinIO, and Qdrant resources.")
    parser.add_argument(
        "--load-model",
        action="store_true",
        help="Also load DINOv2 once to verify model dependencies.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(load_model=args.load_model)


if __name__ == "__main__":
    main()
