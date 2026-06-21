from __future__ import annotations

"""Unit tests for storage_service — LocalStorageClient and mocked StorageClient."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── LocalStorageClient ────────────────────────────────────────────────────────

def test_local_storage_creates_root_dir() -> None:
	from gbedu_api.services.storage_service import LocalStorageClient
	client = LocalStorageClient()
	assert Path("/tmp/gbedu_local_storage").exists()


async def test_local_storage_upload_returns_file_url() -> None:
	from gbedu_api.services.storage_service import LocalStorageClient
	client = LocalStorageClient()
	with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
		f.write(b"fake audio bytes")
		tmp_path = Path(f.name)

	url = await client.upload_audio(tmp_path, "tracks/test-001.mp3")
	assert url.startswith("file://")
	assert "test-001.mp3" in url


async def test_local_storage_upload_asserts_file_exists() -> None:
	from gbedu_api.services.storage_service import LocalStorageClient
	client = LocalStorageClient()
	with pytest.raises(AssertionError, match="not found"):
		await client.upload_audio(Path("/nonexistent/file.mp3"), "tracks/x.mp3")


async def test_local_storage_presigned_url_returns_file_path() -> None:
	from gbedu_api.services.storage_service import LocalStorageClient
	client = LocalStorageClient()
	url = await client.get_presigned_url("tracks/test-001.mp3")
	assert "test-001.mp3" in url


async def test_local_storage_delete_existing_file() -> None:
	from gbedu_api.services.storage_service import LocalStorageClient
	client = LocalStorageClient()
	with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir="/tmp/gbedu_local_storage") as f:
		f.write(b"data")
		tmp = Path(f.name)

	key = tmp.name
	await client.delete_object(key)
	assert not (Path("/tmp/gbedu_local_storage") / key).exists()


async def test_local_storage_delete_nonexistent_is_noop() -> None:
	from gbedu_api.services.storage_service import LocalStorageClient
	client = LocalStorageClient()
	# Should not raise
	await client.delete_object("nonexistent/key.mp3")


async def test_local_storage_upload_creates_parent_dirs() -> None:
	from gbedu_api.services.storage_service import LocalStorageClient
	client = LocalStorageClient()
	with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
		f.write(b"bytes")
		src = Path(f.name)

	key = "deep/nested/dir/track.mp3"
	url = await client.upload_audio(src, key)
	assert "track.mp3" in url


# ── StorageClient ─────────────────────────────────────────────────────────────

def _make_storage_settings():
	s = MagicMock()
	s.r2_account_id = "account-id"
	s.r2_access_key_id = "access-key"
	s.r2_secret_access_key = "secret-key"
	s.r2_bucket_name = "gbedu-audio"
	s.r2_public_url = "https://cdn.example.com"
	s.r2_endpoint_url = "https://r2.example.com"
	return s


async def test_storage_client_upload_returns_public_url() -> None:
	from gbedu_api.services.storage_service import StorageClient
	settings = _make_storage_settings()

	with patch("boto3.client") as mock_boto:
		mock_s3 = MagicMock()
		mock_boto.return_value = mock_s3
		mock_s3.upload_fileobj = MagicMock()

		client = StorageClient(settings)

		with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
			f.write(b"audio")
			tmp = Path(f.name)

		url = await client.upload_audio(tmp, "tracks/test.mp3")

	assert url == "https://cdn.example.com/tracks/test.mp3"


async def test_storage_client_upload_raises_on_missing_file() -> None:
	from gbedu_api.services.storage_service import StorageClient
	settings = _make_storage_settings()

	with patch("boto3.client"):
		client = StorageClient(settings)
		with pytest.raises(AssertionError, match="not found"):
			await client.upload_audio(Path("/no/such/file.mp3"), "key")


async def test_storage_client_upload_raises_on_botocore_error() -> None:
	from gbedu_api.services.storage_service import StorageClient
	from botocore.exceptions import BotoCoreError
	from gbedu_core.errors import StorageUploadError
	settings = _make_storage_settings()

	with patch("boto3.client") as mock_boto:
		mock_s3 = MagicMock()
		mock_boto.return_value = mock_s3
		mock_s3.upload_fileobj.side_effect = BotoCoreError()

		client = StorageClient(settings)

		with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
			f.write(b"bytes")
			tmp = Path(f.name)

		with pytest.raises(StorageUploadError):
			await client.upload_audio(tmp, "tracks/test.mp3")


async def test_storage_client_get_presigned_url() -> None:
	from gbedu_api.services.storage_service import StorageClient
	settings = _make_storage_settings()

	with patch("boto3.client") as mock_boto:
		mock_s3 = MagicMock()
		mock_boto.return_value = mock_s3
		mock_s3.generate_presigned_url.return_value = "https://presigned.example.com/key?sig=abc"

		client = StorageClient(settings)
		url = await client.get_presigned_url("tracks/test.mp3")

	assert "presigned" in url


async def test_storage_client_get_presigned_url_raises_on_empty_key() -> None:
	from gbedu_api.services.storage_service import StorageClient
	settings = _make_storage_settings()

	with patch("boto3.client"):
		client = StorageClient(settings)
		with pytest.raises(AssertionError):
			await client.get_presigned_url("")


async def test_storage_client_delete_object() -> None:
	from gbedu_api.services.storage_service import StorageClient
	settings = _make_storage_settings()

	with patch("boto3.client") as mock_boto:
		mock_s3 = MagicMock()
		mock_boto.return_value = mock_s3

		client = StorageClient(settings)
		await client.delete_object("tracks/test.mp3")

	mock_s3.delete_object.assert_called_once()


async def test_storage_client_delete_raises_on_empty_key() -> None:
	from gbedu_api.services.storage_service import StorageClient
	settings = _make_storage_settings()

	with patch("boto3.client"):
		client = StorageClient(settings)
		with pytest.raises(AssertionError):
			await client.delete_object("")


async def test_storage_client_delete_raises_storage_error_on_boto_failure() -> None:
	from gbedu_api.services.storage_service import StorageClient
	from botocore.exceptions import ClientError
	from gbedu_core.errors import StorageDeleteError
	settings = _make_storage_settings()

	with patch("boto3.client") as mock_boto:
		mock_s3 = MagicMock()
		mock_boto.return_value = mock_s3
		mock_s3.delete_object.side_effect = ClientError(
			{"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "delete_object"
		)

		client = StorageClient(settings)
		with pytest.raises(StorageDeleteError):
			await client.delete_object("tracks/test.mp3")


def test_storage_client_init_asserts_settings() -> None:
	from gbedu_api.services.storage_service import StorageClient
	from unittest.mock import MagicMock
	bad = MagicMock()
	bad.r2_account_id = ""
	bad.r2_access_key_id = "key"
	bad.r2_secret_access_key = "secret"
	bad.r2_bucket_name = "bucket"
	with pytest.raises(AssertionError, match="R2_ACCOUNT_ID"):
		StorageClient(bad)
