"""S3-compatible storage client (MinIO in development, S3 in production).

The minio SDK is synchronous; presigning is pure local HMAC computation (no
network), so it is safe to call from async handlers. Object operations (stat,
remove) touch the network and are therefore wrapped in run_in_threadpool.
One client instance per process, created via a FastAPI dependency.
"""

from datetime import timedelta

from minio import Minio
from starlette.concurrency import run_in_threadpool

from app.core.config import settings


class StorageClient:
    def __init__(self, client: Minio, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_settings(cls) -> "StorageClient":
        client = Minio(
            settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            secure=settings.s3_secure,
        )
        return cls(client, settings.s3_bucket)

    def presign_put(self, key: str, content_type: str | None = None) -> str:
        return self.client.presigned_put_object(
            self.bucket, key, expires=timedelta(seconds=settings.s3_presign_expiry_seconds)
        )

    def presign_get(self, key: str) -> str:
        return self.client.presigned_get_object(
            self.bucket, key, expires=timedelta(seconds=settings.s3_presign_expiry_seconds)
        )

    async def stat(self, key: str) -> dict | None:
        """Async wrapper over blocking network I/O. None if object missing."""

        from minio.error import S3Error

        try:
            return await run_in_threadpool(self._stat_sync, key)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                return None
            raise

    def _stat_sync(self, key: str) -> dict:
        stat = self.client.stat_object(self.bucket, key)
        return {"size": stat.size, "etag": stat.etag}

    def remove(self, key: str) -> None:
        """Best-effort delete; storage must not block business flows."""
        try:
            self.client.remove_object(self.bucket, key)
        except Exception:
            import logging

            logging.getLogger(__name__).warning("Failed to delete object %s", key)

    async def ensure_bucket(self, attempts: int = 1, delay_seconds: float = 1.0) -> None:
        """Startup convenience: create the bucket if missing.

        Retries briefly so an API container that won the race against a
        just-started MinIO/S3 endpoint still provisions the bucket; after
        `attempts` it logs and continues (storage is not startup-critical).
        """
        import asyncio
        import logging

        for attempt in range(1, attempts + 1):
            try:
                exists = await run_in_threadpool(self.client.bucket_exists, self.bucket)
                if not exists:
                    await run_in_threadpool(self.client.make_bucket, self.bucket)
                return
            except Exception:
                if attempt >= attempts:
                    logging.getLogger(__name__).warning(
                        "Object storage unreachable at startup; continuing without it"
                    )
                    return
                await asyncio.sleep(delay_seconds)
