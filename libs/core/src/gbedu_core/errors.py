from __future__ import annotations

from http import HTTPStatus
from typing import Any

# ── Error code constants ───────────────────────────────────────────────────────

EC_VALIDATION = "VALIDATION_ERROR"
EC_AUTHENTICATION = "AUTHENTICATION_ERROR"
EC_AUTHORIZATION = "AUTHORIZATION_ERROR"
EC_NOT_FOUND = "NOT_FOUND"
EC_CONFLICT = "CONFLICT"
EC_RATE_LIMIT = "RATE_LIMIT_EXCEEDED"
EC_PAYMENT = "PAYMENT_ERROR"
EC_PAYMENT_DECLINED = "PAYMENT_DECLINED"
EC_PAYMENT_WEBHOOK = "PAYMENT_WEBHOOK_ERROR"
EC_STORAGE = "STORAGE_ERROR"
EC_STORAGE_UPLOAD = "STORAGE_UPLOAD_ERROR"
EC_STORAGE_DELETE = "STORAGE_DELETE_ERROR"
EC_ML_SERVICE = "ML_SERVICE_ERROR"
EC_ML_TIMEOUT = "ML_SERVICE_TIMEOUT"
EC_GENERATION = "GENERATION_ERROR"
EC_GENERATION_QUOTA = "GENERATION_QUOTA_EXCEEDED"
EC_WORKER = "WORKER_ERROR"
EC_WORKER_TIMEOUT = "WORKER_TIMEOUT"
EC_DATABASE = "DATABASE_ERROR"
EC_DATABASE_CONNECTION = "DATABASE_CONNECTION_ERROR"
EC_DATABASE_INTEGRITY = "DATABASE_INTEGRITY_ERROR"
EC_TOKEN_EXPIRED = "TOKEN_EXPIRED"
EC_TOKEN_INVALID = "TOKEN_INVALID"
EC_INVALID_CREDENTIALS = "INVALID_CREDENTIALS"


class GbeduError(Exception):
	"""Base error for all Gbẹdu application exceptions."""

	error_code: str = "GBEDU_ERROR"
	http_status: int = HTTPStatus.INTERNAL_SERVER_ERROR

	def __init__(
		self,
		message: str,
		*,
		error_code: str | None = None,
		details: dict[str, Any] | None = None,
	) -> None:
		super().__init__(message)
		self.message = message
		self.details: dict[str, Any] = details or {}
		if error_code is not None:
			self.error_code = error_code

	def __repr__(self) -> str:
		return (
			f"{self.__class__.__name__}("
			f"error_code={self.error_code!r}, "
			f"message={self.message!r}, "
			f"details={self.details!r})"
		)

	def to_dict(self) -> dict[str, Any]:
		return {
			"error_code": self.error_code,
			"message": self.message,
			"details": self.details,
		}


class ValidationError(GbeduError):
	error_code = EC_VALIDATION
	http_status = HTTPStatus.UNPROCESSABLE_ENTITY

	def __init__(
		self, message: str, *, field: str | None = None, details: dict[str, Any] | None = None
	) -> None:
		d = details or {}
		if field is not None:
			d["field"] = field
		super().__init__(message, details=d)


class AuthenticationError(GbeduError):
	error_code = EC_AUTHENTICATION
	http_status = HTTPStatus.UNAUTHORIZED

	def __init__(
		self, message: str = "Authentication required", *, details: dict[str, Any] | None = None
	) -> None:
		super().__init__(message, details=details)


class TokenExpiredError(AuthenticationError):
	error_code = EC_TOKEN_EXPIRED

	def __init__(self, message: str = "Token has expired") -> None:
		super().__init__(message)


class TokenInvalidError(AuthenticationError):
	error_code = EC_TOKEN_INVALID

	def __init__(self, message: str = "Token is invalid") -> None:
		super().__init__(message)


class InvalidCredentialsError(AuthenticationError):
	error_code = EC_INVALID_CREDENTIALS

	def __init__(self, message: str = "Invalid email or password") -> None:
		super().__init__(message)


class AuthorizationError(GbeduError):
	error_code = EC_AUTHORIZATION
	http_status = HTTPStatus.FORBIDDEN

	def __init__(
		self, message: str = "Insufficient permissions", *, details: dict[str, Any] | None = None
	) -> None:
		super().__init__(message, details=details)


class NotFoundError(GbeduError):
	error_code = EC_NOT_FOUND
	http_status = HTTPStatus.NOT_FOUND

	def __init__(self, resource: str, identifier: str | None = None) -> None:
		detail = f"{resource} not found"
		if identifier is not None:
			detail = f"{resource} '{identifier}' not found"
		super().__init__(detail, details={"resource": resource, "identifier": identifier})


class ConflictError(GbeduError):
	error_code = EC_CONFLICT
	http_status = HTTPStatus.CONFLICT

	def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
		super().__init__(message, details=details)


class RateLimitError(GbeduError):
	error_code = EC_RATE_LIMIT
	http_status = HTTPStatus.TOO_MANY_REQUESTS

	def __init__(
		self,
		message: str = "Rate limit exceeded",
		*,
		retry_after_seconds: int | None = None,
		details: dict[str, Any] | None = None,
	) -> None:
		d = details or {}
		if retry_after_seconds is not None:
			d["retry_after_seconds"] = retry_after_seconds
		super().__init__(message, details=d)
		self.retry_after_seconds = retry_after_seconds


class PaymentError(GbeduError):
	error_code = EC_PAYMENT
	http_status = HTTPStatus.PAYMENT_REQUIRED

	def __init__(
		self, message: str, *, provider: str | None = None, details: dict[str, Any] | None = None
	) -> None:
		d = details or {}
		if provider is not None:
			d["provider"] = provider
		super().__init__(message, details=d)


class PaymentDeclinedError(PaymentError):
	error_code = EC_PAYMENT_DECLINED

	def __init__(
		self, message: str = "Payment was declined", *, provider: str | None = None
	) -> None:
		super().__init__(message, provider=provider)


class PaymentWebhookError(PaymentError):
	error_code = EC_PAYMENT_WEBHOOK
	http_status = HTTPStatus.BAD_REQUEST

	def __init__(self, message: str, *, provider: str | None = None) -> None:
		super().__init__(message, provider=provider)


class StorageError(GbeduError):
	error_code = EC_STORAGE
	http_status = HTTPStatus.INTERNAL_SERVER_ERROR

	def __init__(
		self, message: str, *, path: str | None = None, details: dict[str, Any] | None = None
	) -> None:
		d = details or {}
		if path is not None:
			d["path"] = path
		super().__init__(message, details=d)


class StorageUploadError(StorageError):
	error_code = EC_STORAGE_UPLOAD


class StorageDeleteError(StorageError):
	error_code = EC_STORAGE_DELETE


class MLServiceError(GbeduError):
	error_code = EC_ML_SERVICE
	http_status = HTTPStatus.BAD_GATEWAY

	def __init__(
		self, message: str, *, model: str | None = None, details: dict[str, Any] | None = None
	) -> None:
		d = details or {}
		if model is not None:
			d["model"] = model
		super().__init__(message, details=d)


class MLServiceTimeoutError(MLServiceError):
	error_code = EC_ML_TIMEOUT
	http_status = HTTPStatus.GATEWAY_TIMEOUT

	def __init__(self, message: str = "ML service timed out", *, model: str | None = None) -> None:
		super().__init__(message, model=model)


class GenerationError(MLServiceError):
	error_code = EC_GENERATION

	def __init__(
		self,
		message: str,
		*,
		model: str | None = None,
		job_id: str | None = None,
		details: dict[str, Any] | None = None,
	) -> None:
		d = details or {}
		if job_id is not None:
			d["job_id"] = job_id
		super().__init__(message, model=model, details=d)


class GenerationQuotaError(GenerationError):
	error_code = EC_GENERATION_QUOTA
	http_status = HTTPStatus.TOO_MANY_REQUESTS

	def __init__(self, tier: str, daily_limit: int) -> None:
		super().__init__(
			f"Daily generation limit of {daily_limit} reached for {tier} tier",
			details={"tier": tier, "daily_limit": daily_limit},
		)


class WorkerError(GbeduError):
	error_code = EC_WORKER
	http_status = HTTPStatus.INTERNAL_SERVER_ERROR

	def __init__(
		self, message: str, *, task_id: str | None = None, details: dict[str, Any] | None = None
	) -> None:
		d = details or {}
		if task_id is not None:
			d["task_id"] = task_id
		super().__init__(message, details=d)


class WorkerTimeoutError(WorkerError):
	error_code = EC_WORKER_TIMEOUT
	http_status = HTTPStatus.GATEWAY_TIMEOUT

	def __init__(self, task_id: str | None = None) -> None:
		super().__init__("Worker task timed out", task_id=task_id)


class DatabaseError(GbeduError):
	error_code = EC_DATABASE
	http_status = HTTPStatus.INTERNAL_SERVER_ERROR

	def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
		super().__init__(message, details=details)


class DatabaseConnectionError(DatabaseError):
	error_code = EC_DATABASE_CONNECTION

	def __init__(self, message: str = "Could not connect to database") -> None:
		super().__init__(message)


class DatabaseIntegrityError(DatabaseError):
	error_code = EC_DATABASE_INTEGRITY
	http_status = HTTPStatus.CONFLICT

	def __init__(self, message: str, *, constraint: str | None = None) -> None:
		d: dict[str, Any] = {}
		if constraint is not None:
			d["constraint"] = constraint
		super().__init__(message, details=d)
