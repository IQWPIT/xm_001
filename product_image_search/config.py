from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "product_search"
    mongo_collection: str = "products"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "product-images"

    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "product_image_vectors"

    model_name: str = "facebook/dinov2-small"
    device: str = Field(default="auto", description="auto, cpu, cuda, or mps")
    batch_size: int = 16
    request_timeout_seconds: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
