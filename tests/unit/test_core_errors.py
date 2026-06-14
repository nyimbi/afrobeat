"""Unit tests for the GbeduError hierarchy: HTTP statuses, error codes, details."""
from __future__ import annotations

from http import HTTPStatus

import pytest

from gbedu_core.errors import (
	AuthenticationError,
	AuthorizationError,
	ConflictError,
	DatabaseConnectionError,
	DatabaseError,
	DatabaseIntegrityError,
	GbeduError,
	GenerationError,
	GenerationQuotaError,
	InvalidCredentialsError,
	MLServiceError,
	MLServiceTimeoutError,
	NotFoundError,
	PaymentDeclinedError,
	PaymentError,
	PaymentWebhookError,
	RateLimitError,
	StorageDeleteError,
	StorageError,
	StorageUploadError,
	TokenExpiredError,
	TokenInvalidError,
	ValidationError,
	WorkerError,
	WorkerTimeoutError,
)


# ── Base class ─────────────────────────────────────────────────────────────────

def test_gbedu_error_base():
	e = GbeduError("something went wrong")
	assert str(e) == "something went wrong"
	assert e.error_code == "GBEDU_ERROR"
	assert e.http_status == HTTPStatus.INTERNAL_SERVER_ERROR
	assert e.details == {}


def test_gbedu_error_with_details():
	e = GbeduError("oops", details={"key": "value"})
	assert e.details == {"key": "value"}


def test_gbedu_error_to_dict():
	e = GbeduError("fail", details={"x": 1})
	d = e.to_dict()
	assert d["error_code"] == "GBEDU_ERROR"
	assert d["message"] == "fail"
	assert d["details"] == {"x": 1}


def test_gbedu_error_custom_error_code():
	e = GbeduError("fail", error_code="CUSTOM")
	assert e.error_code == "CUSTOM"


# ── Authentication ─────────────────────────────────────────────────────────────

def test_authentication_error():
	e = AuthenticationError()
	assert e.http_status == HTTPStatus.UNAUTHORIZED
	assert e.error_code == "AUTHENTICATION_ERROR"


def test_token_expired_error():
	e = TokenExpiredError()
	assert e.error_code == "TOKEN_EXPIRED"
	assert e.http_status == HTTPStatus.UNAUTHORIZED


def test_token_invalid_error():
	e = TokenInvalidError()
	assert e.error_code == "TOKEN_INVALID"
	assert e.http_status == HTTPStatus.UNAUTHORIZED


def test_invalid_credentials_error():
	e = InvalidCredentialsError()
	assert e.error_code == "INVALID_CREDENTIALS"
	assert e.http_status == HTTPStatus.UNAUTHORIZED


# ── Authorization ──────────────────────────────────────────────────────────────

def test_authorization_error():
	e = AuthorizationError()
	assert e.http_status == HTTPStatus.FORBIDDEN
	assert e.error_code == "AUTHORIZATION_ERROR"


# ── Validation ─────────────────────────────────────────────────────────────────

def test_validation_error():
	e = ValidationError("bad input", field="email")
	assert e.http_status == HTTPStatus.UNPROCESSABLE_ENTITY
	assert e.details["field"] == "email"


def test_validation_error_no_field():
	e = ValidationError("bad input")
	assert "field" not in e.details


# ── Not Found ──────────────────────────────────────────────────────────────────

def test_not_found_error_with_identifier():
	e = NotFoundError("User", "abc-123")
	assert e.http_status == HTTPStatus.NOT_FOUND
	assert "abc-123" in e.message
	assert e.details["resource"] == "User"
	assert e.details["identifier"] == "abc-123"


def test_not_found_error_without_identifier():
	e = NotFoundError("Track")
	assert "Track not found" in e.message
	assert e.details["identifier"] is None


# ── Conflict ───────────────────────────────────────────────────────────────────

def test_conflict_error():
	e = ConflictError("email already registered")
	assert e.http_status == HTTPStatus.CONFLICT
	assert e.error_code == "CONFLICT"


# ── Rate Limit ─────────────────────────────────────────────────────────────────

def test_rate_limit_error_with_retry_after():
	e = RateLimitError(retry_after_seconds=60)
	assert e.http_status == HTTPStatus.TOO_MANY_REQUESTS
	assert e.retry_after_seconds == 60
	assert e.details["retry_after_seconds"] == 60


def test_rate_limit_error_without_retry_after():
	e = RateLimitError()
	assert e.retry_after_seconds is None


# ── Payment ────────────────────────────────────────────────────────────────────

def test_payment_error():
	e = PaymentError("charge failed", provider="stripe")
	assert e.http_status == HTTPStatus.PAYMENT_REQUIRED
	assert e.details["provider"] == "stripe"


def test_payment_declined_error():
	e = PaymentDeclinedError(provider="paystack")
	assert e.error_code == "PAYMENT_DECLINED"


def test_payment_webhook_error():
	e = PaymentWebhookError("bad signature", provider="stripe")
	assert e.http_status == HTTPStatus.BAD_REQUEST
	assert e.error_code == "PAYMENT_WEBHOOK_ERROR"


# ── Storage ────────────────────────────────────────────────────────────────────

def test_storage_error_with_path():
	e = StorageError("upload failed", path="/audio/track.mp3")
	assert e.details["path"] == "/audio/track.mp3"


def test_storage_upload_error():
	e = StorageUploadError("timeout", path="bucket/key")
	assert e.error_code == "STORAGE_UPLOAD_ERROR"


def test_storage_delete_error():
	e = StorageDeleteError("not found", path="bucket/missing")
	assert e.error_code == "STORAGE_DELETE_ERROR"


# ── ML Service ─────────────────────────────────────────────────────────────────

def test_ml_service_error():
	e = MLServiceError("inference failed", model="udio-v2")
	assert e.http_status == HTTPStatus.BAD_GATEWAY
	assert e.details["model"] == "udio-v2"


def test_ml_service_timeout_error():
	e = MLServiceTimeoutError(model="udio-v2")
	assert e.http_status == HTTPStatus.GATEWAY_TIMEOUT
	assert e.error_code == "ML_SERVICE_TIMEOUT"


def test_generation_error_with_job_id():
	e = GenerationError("stem separation failed", job_id="job-abc")
	assert e.details["job_id"] == "job-abc"


def test_generation_quota_error():
	e = GenerationQuotaError(tier="free", daily_limit=3)
	assert e.http_status == HTTPStatus.TOO_MANY_REQUESTS
	assert e.error_code == "GENERATION_QUOTA_EXCEEDED"
	assert "3" in e.message
	assert e.details["daily_limit"] == 3


# ── Worker ─────────────────────────────────────────────────────────────────────

def test_worker_error_with_task_id():
	e = WorkerError("task failed", task_id="celery-xyz")
	assert e.details["task_id"] == "celery-xyz"


def test_worker_timeout_error():
	e = WorkerTimeoutError(task_id="t-123")
	assert e.http_status == HTTPStatus.GATEWAY_TIMEOUT
	assert e.error_code == "WORKER_TIMEOUT"


# ── Database ───────────────────────────────────────────────────────────────────

def test_database_error():
	e = DatabaseError("query failed")
	assert e.http_status == HTTPStatus.INTERNAL_SERVER_ERROR


def test_database_connection_error():
	e = DatabaseConnectionError()
	assert e.error_code == "DATABASE_CONNECTION_ERROR"


def test_database_integrity_error_with_constraint():
	e = DatabaseIntegrityError("duplicate key", constraint="uq_users_email")
	assert e.http_status == HTTPStatus.CONFLICT
	assert e.details["constraint"] == "uq_users_email"


# ── Inheritance ────────────────────────────────────────────────────────────────

def test_all_errors_are_gbedu_error():
	errors = [
		ValidationError("x"),
		AuthenticationError(),
		TokenExpiredError(),
		TokenInvalidError(),
		AuthorizationError(),
		NotFoundError("X"),
		ConflictError("x"),
		RateLimitError(),
		PaymentError("x"),
		StorageError("x"),
		MLServiceError("x"),
		WorkerError("x"),
		DatabaseError("x"),
	]
	for e in errors:
		assert isinstance(e, GbeduError), f"{type(e).__name__} must extend GbeduError"
		assert isinstance(e, Exception)
