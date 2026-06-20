from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from circuitbreaker import CircuitBreaker, CircuitBreakerError

from gbedu_core.config import StorageSettings
from gbedu_core.errors import StorageDeleteError, StorageError, StorageUploadError

log = structlog.get_logger(__name__)

# Storage circuit breaker — trips after 5 consecutive S3/R2 failures, recovers after 60 s.
# Prevents cascading timeouts when R2 is unavailable.
_STORAGE_CIRCUIT_FAILURE_THRESHOLD = 5
_STORAGE_CIRCUIT_RECOVERY_TIMEOUT = 60

_RETRY_KWARGS: dict[str, Any] = dict(
	retry=retry_if_exception_type((BotoCoreError, ClientError)),
	wait=wait_exponential(multiplier=1, min=1, max=10),
	stop=stop_after_attempt(3),
	reraise=True,
)


class LocalStorageClient:
	"""Filesystem-backed storage for local dev (no R2 credentials needed).

	Files are written to /tmp/gbedu_local_storage/ and served via a local
	file URL. Not for production — never handles auth or CDN.
	"""

	def __init__(self) -> None:
		self._root = Path("/tmp/gbedu_local_storage")
		self._root.mkdir(parents=True, exist_ok=True)
		log.warning("storage.local_mode", root=str(self._root))

	async def upload_audio(self, file_path: Path, key: str, content_type: str = "audio/mpeg") -> str:
		assert file_path.exists(), f"file not found: {file_path}"
		dest = self._root / key
		dest.parent.mkdir(parents=True, exist_ok=True)
		import shutil
		shutil.copy2(file_path, dest)
		url = f"file://{dest}"
		log.info("storage.local.uploaded", key=key, url=url)
		return url

	async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
		return f"file://{self._root / key}"

	async def delete_object(self, key: str) -> None:
		target = self._root / key
		if target.exists():
			target.unlink()
		log.info("storage.local.deleted", key=key)


class StorageClient:
	"""Async-safe wrapper around boto3 S3 client targeting Cloudflare R2.

	boto3 is synchronous — all operations are dispatched to a thread pool
	via asyncio.get_event_loop().run_in_executor so the event loop is never blocked.
	"""

	def __init__(self, settings: StorageSettings) -> None:
		assert settings.r2_account_id, "R2_ACCOUNT_ID must be set"
		assert settings.r2_access_key_id, "R2_ACCESS_KEY_ID must be set"
		assert settings.r2_secret_access_key, "R2_SECRET_ACCESS_KEY must be set"
		assert settings.r2_bucket_name, "R2_BUCKET_NAME must be set"

		self._bucket = settings.r2_bucket_name
		self._public_url = settings.r2_public_url.rstrip("/")
		self._client = boto3.client(
			"s3",
			endpoint_url=settings.r2_endpoint_url,
			aws_access_key_id=settings.r2_access_key_id,
			aws_secret_access_key=settings.r2_secret_access_key,
			region_name="auto",
		)
		self._circuit = CircuitBreaker(
			failure_threshold=_STORAGE_CIRCUIT_FAILURE_THRESHOLD,
			recovery_timeout=_STORAGE_CIRCUIT_RECOVERY_TIMEOUT,
			name="storage",
		)

	async def upload_audio(
		self,
		file_path: Path,
		key: str,
		content_type: str = "audio/mpeg",
	) -> str:
		"""Upload a local file to R2 and return its public URL."""
		assert file_path.exists(), f"file not found: {file_path}"
		assert key, "key must not be empty"

		log.info("storage.upload.start", key=key, path=str(file_path))

		@retry(**_RETRY_KWARGS)
		def _upload() -> None:
			with open(file_path, "rb") as fh:
				self._client.upload_fileobj(
					fh,
					self._bucket,
					key,
					ExtraArgs={"ContentType": content_type},
				)

		try:
			loop = asyncio.get_event_loop()
			await loop.run_in_executor(None, self._circuit(_upload))
		except CircuitBreakerError as exc:
			log.error("storage.circuit_open", key=key)
			raise StorageUploadError("Storage circuit breaker open — R2 unavailable", path=key) from exc
		except (BotoCoreError, ClientError) as exc:
			log.error("storage.upload.failed", key=key, error=str(exc))
			raise StorageUploadError(f"Failed to upload {key}", path=key) from exc

		url = f"{self._public_url}/{key}"
		log.info("storage.upload.complete", key=key, url=url)
		return url

	async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
		"""Return a time-limited presigned GET URL for a private R2 object."""
		assert key, "key must not be empty"
		assert expires_in > 0, "expires_in must be positive"

		@retry(**_RETRY_KWARGS)
		def _presign() -> str:
			return self._client.generate_presigned_url(
				"get_object",
				Params={"Bucket": self._bucket, "Key": key},
				ExpiresIn=expires_in,
			)

		try:
			loop = asyncio.get_event_loop()
			url = await loop.run_in_executor(None, self._circuit(_presign))
		except CircuitBreakerError as exc:
			log.error("storage.circuit_open", key=key)
			raise StorageError("Storage circuit breaker open — R2 unavailable", path=key) from exc
		except (BotoCoreError, ClientError) as exc:
			log.error("storage.presign.failed", key=key, error=str(exc))
			raise StorageError(f"Failed to generate presigned URL for {key}", path=key) from exc

		return url

	async def delete_object(self, key: str) -> None:
		"""Delete an object from R2. Idempotent — 404 is not an error."""
		assert key, "key must not be empty"

		@retry(**_RETRY_KWARGS)
		def _delete() -> None:
			self._client.delete_object(Bucket=self._bucket, Key=key)

		try:
			loop = asyncio.get_event_loop()
			await loop.run_in_executor(None, self._circuit(_delete))
		except CircuitBreakerError as exc:
			log.error("storage.circuit_open", key=key)
			raise StorageDeleteError("Storage circuit breaker open — R2 unavailable", path=key) from exc
		except (BotoCoreError, ClientError) as exc:
			log.error("storage.delete.failed", key=key, error=str(exc))
			raise StorageDeleteError(f"Failed to delete {key}", path=key) from exc

		log.info("storage.delete.complete", key=key)
