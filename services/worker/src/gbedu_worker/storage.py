from __future__ import annotations

"""Cloudflare R2 upload client used by generation and audio tasks."""

import asyncio
from typing import Any

import structlog
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from gbedu_core.config import StorageSettings
from gbedu_worker.exceptions import UploadError

log = structlog.get_logger(__name__)


class R2Client:
	"""Async wrapper around boto3 S3 client pointing at Cloudflare R2."""

	def __init__(self, settings: StorageSettings) -> None:
		self._settings = settings

	def _make_client(self) -> Any:
		import boto3
		return boto3.client(
			"s3",
			endpoint_url=self._settings.r2_endpoint_url,
			aws_access_key_id=self._settings.r2_access_key_id,
			aws_secret_access_key=self._settings.r2_secret_access_key,
			region_name="auto",
		)

	async def upload(self, *, key: str, data: bytes, content_type: str) -> str:
		"""Upload bytes to R2 and return the public CDN URL.

		Retries up to 3 times with exponential back-off before raising UploadError.
		"""
		assert key, "R2 key must not be empty"
		assert data, "upload data must not be empty"

		async for attempt in AsyncRetrying(
			stop=stop_after_attempt(3),
			wait=wait_exponential(multiplier=2, min=2, max=30),
			retry=retry_if_exception_type(UploadError),
			reraise=True,
		):
			with attempt:
				try:
					await self._put(key, data, content_type)
				except Exception as exc:
					log.warning("r2 upload attempt failed", key=key, exc=str(exc))
					raise UploadError(f"R2 upload failed for key={key!r}: {exc}") from exc

		url = f"{self._settings.r2_public_url}/{key}"
		log.debug("r2 upload complete", key=key, url=url, size_bytes=len(data))
		return url

	async def _put(self, key: str, data: bytes, content_type: str) -> None:
		client = self._make_client()
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(
			None,
			lambda: client.put_object(
				Bucket=self._settings.r2_bucket_name,
				Key=key,
				Body=data,
				ContentType=content_type,
				CacheControl="public, max-age=31536000, immutable",
			),
		)

	async def delete(self, *, key: str) -> None:
		"""Delete a single object from R2. No-op if the key does not exist."""
		client = self._make_client()
		loop = asyncio.get_event_loop()
		try:
			await loop.run_in_executor(
				None,
				lambda: client.delete_object(
					Bucket=self._settings.r2_bucket_name,
					Key=key,
				),
			)
			log.debug("r2 delete complete", key=key)
		except Exception as exc:
			log.warning("r2 delete failed", key=key, exc=str(exc))
			raise UploadError(f"R2 delete failed for key={key!r}: {exc}") from exc

	async def generate_presigned_url(self, *, key: str, expires_in: int = 3600) -> str:
		"""Generate a time-limited pre-signed GET URL for private objects."""
		assert key, "key must not be empty"
		assert expires_in > 0, "expires_in must be positive"

		client = self._make_client()
		loop = asyncio.get_event_loop()
		url: str = await loop.run_in_executor(
			None,
			lambda: client.generate_presigned_url(
				"get_object",
				Params={"Bucket": self._settings.r2_bucket_name, "Key": key},
				ExpiresIn=expires_in,
			),
		)
		return url
