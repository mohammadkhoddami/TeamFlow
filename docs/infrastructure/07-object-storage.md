# Infrastructure 07 — Object Storage (MinIO / S3)

## Concept

Files live in object storage (S3-compatible; MinIO locally); the database stores
**metadata only**. Clients upload/download directly against storage using
**presigned URLs** — the API never proxies bytes.

## Why not store files in Postgres or on the API disk

| Approach | Problems |
| --- | --- |
| Bytes in Postgres | bloats the DB, WAL amplification, backups huge, no CDN path |
| Local disk on API workers | no sharing across workers/containers, lost on redeploy |
| **S3 + presigned URLs** | API stays stateless; storage scales independently |

## The flow

```
1. POST /tasks/{id}/attachments         → validate metadata, create PENDING row,
                                          return presigned PUT URL
2. client PUTs bytes to MinIO directly  → (API never sees the file)
3. POST .../attachments/{id}/confirm    → storage.stat() HEAD check → AVAILABLE
4. POST /attachments/{id}/download-url  → presigned GET URL
```

Metadata row (`app/models/attachment.py`): `filename`, `content_type`, `size`,
`storage_key`, `status`, `uploader_id`, `task_id`, `organization_id`,
timestamps.

## The storage client — `app/services/integrations/storage.py`

```python
class StorageClient:
    @classmethod
    def from_settings(cls) -> "StorageClient":
        client = Minio(settings.s3_endpoint, access_key=..., secret_key=...,
                       secure=settings.s3_secure)
        return cls(client, settings.s3_bucket)

    def presign_put(self, key: str, content_type: str | None = None) -> str:
        return self.client.presigned_put_object(
            self.bucket, key, expires=timedelta(seconds=settings.s3_presign_expiry_seconds))

    def presign_get(self, key: str) -> str: ...

    async def stat(self, key: str) -> dict | None:
        """Async wrapper over blocking network I/O. None if object missing."""
        try:
            return await run_in_threadpool(self._stat_sync, key)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
                return None
            raise

    def remove(self, key: str) -> None: ...          # best-effort

    async def ensure_bucket(self) -> None: ...        # dev bootstrap, non-fatal
```

Async discipline (`async/04-async-in-teamflow.md`):

- **Presigning is pure local HMAC** — microseconds of CPU, no socket. Safe
  inline in async handlers.
- **`stat`/`remove` touch the network** — offloaded via `run_in_threadpool`
  (stat) or documented best-effort (remove).
- **`ensure_bucket`** runs in lifespan, skips in tests, and swallows failures —
  storage being down must not stop the API from booting.

## Upload security — the full checklist

| Threat | Control | Where |
| --- | --- | --- |
| Oversized files | `upload_max_bytes` (10 MB) validated at intent + Pydantic `le=10485760` | `app/services/attachments.py`, schema |
| Malicious content types | allow-list (`image/*`, pdf, text, office, zip) | `settings.upload_allowed_content_types` |
| Path traversal filenames | `sanitize_filename` → basename, `[^A-Za-z0-9._-]` → `_` | `app/services/attachments.py` |
| Client-controlled storage layout | server-generated key: `orgs/{org}/tasks/{task}/{uuid}{ext}` | `build_storage_key` |
| Cross-tenant access | `TaskAccess` dependency on every attachment route | `app/api/routes/attachments.py` |
| Guessing objects in the bucket | presigned URLs only; bucket stays private | storage config |
| Unbounded access after sharing | presign expiry (`s3_presign_expiry_seconds`, default 900) | settings |
| Orphaned uploads | confirm-then-available + cleanup task deletes stale PENDING rows/objects | `app/workers/tasks.py` |

Validation function:

```python
def validate_upload(filename: str, content_type: str, size: int) -> None:
    if size <= 0 or size > settings.upload_max_bytes:
        raise ValidationFailedError(f"File size must be between 1 byte and ...")
    if content_type not in settings.upload_allowed_content_types:
        raise ValidationFailedError(f"Content type '{content_type}' is not allowed")
    if not sanitize_filename(filename):
        raise ValidationFailedError("Invalid filename")
```

⚠️ Honest gaps (documented, not hidden):

- **Content-Type is client-declared.** Presigned PUT sets the header but MinIO
  does not verify bytes match. Real enforcement (magic-byte sniffing) needs
  either server-side proxy upload or a post-upload scan job. TeamFlow stores
  the declared type and serves it back with `Content-Type` on download —
  which is why the allow-list matters.
- **No antivirus scanning.** Standard production add-on (ClamAV lambda /
  worker scan).
- **DELETE of an org leaves attachment objects orphaned** — rows cascade, bytes
  remain until manual/space-driven cleanup (`auth/07-multi-tenancy.md`).

## The confirm step (`app/services/attachments.py`)

```python
try:
    stored = await storage.stat(attachment.storage_key)
except Exception as exc:
    attachment.status = AttachmentStatus.FAILED
    ...
    raise ValidationFailedError("Object not found in storage; upload the file first") from exc
if stored is None:
    attachment.status = AttachmentStatus.FAILED
    ...
    raise ValidationFailedError("Object not found in storage; upload the file first")

attachment.status = AttachmentStatus.AVAILABLE
```

Confirmation is a HEAD against storage — the server verifies the object exists
before declaring the attachment usable. Retrying after a failed confirm is
allowed (PENDING *or* FAILED states may transition on a successful stat), which
the tests exercise (`tests/integration/test_attachments.py::test_attachment_flow_pending_confirm_download`).

## Test seam

```python
class FakeStorage:
    def presign_put(self, key, content_type=None): return f"http://fake-storage/{key}"
    async def stat(self, key): return {"size": 1} if key in self.keys else None
app.dependency_overrides[get_storage] = lambda: storage
```

Because routes obtain storage through `Depends(get_storage)`, the whole storage
path is replaceable — no MinIO in the test suite (`architecture/03-dependencies.md`).

## Django/DRF comparison 🔵

| Django | TeamFlow |
| --- | --- |
| `FileField` + `MEDIA_ROOT` (local disk by default) | S3/MinIO with metadata row |
| `django-storages` S3 backend | `StorageClient` (explicit presigning) |
| Multipart upload through the view | direct-to-storage presigned PUT/GET |
| DRF `FileUploadParser` | JSON metadata + separate binary PUT |
| `MEDIA_URL` served by Django/nginx | presigned URLs, private bucket |

Django's default path (proxy through the app) is simpler to build and worse to
scale; the presigned pattern is the production standard for file-heavy APIs.

## Review questions

1. Why does the API never see the file bytes, and what does that buy?
2. What exactly does `confirm_upload` verify, and why is that check needed if
   presigning succeeded?
3. Trace a path-traversal filename (`../../etc/passwd.txt`) through
   `sanitize_filename` and the eventual storage key.
4. Name the three honest security gaps in this implementation and the
   production remedy for each.
