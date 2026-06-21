"""Unit tests for /api/v1/contact/* route handler.

Strategy:
- No auth required on this endpoint — override nothing.
- Patch _send_smtp to avoid real SMTP connections.
- Test success path, SMTP failure (502), and validation errors (422).
- No @pytest.mark.asyncio — asyncio_mode = "auto" is set project-wide.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from starlette.testclient import TestClient

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost/gbedu_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GBEDU_ML_API_KEY", "test-ml-internal-api-key")


# ── Helpers ────────────────────────────────────────────────────────────────────

_VALID_PAYLOAD = {
	"name": "Funmilayo Okonkwo",
	"email": "funmi@example.com",
	"subject": "Collaboration request",
	"message": "Hi there, I would love to collaborate on a new afropop track with Gbẹdu.",
}


def _build_client():
	from gbedu_api.main import app

	client = TestClient(app, raise_server_exceptions=False)
	return client


def teardown_function() -> None:
	from gbedu_api.main import app

	app.dependency_overrides.clear()


# ── POST /contact ──────────────────────────────────────────────────────────────


def test_submit_contact_success_returns_received() -> None:
	client = _build_client()

	with patch("gbedu_api.routers.contact._send_smtp") as mock_smtp:
		resp = client.post("/api/v1/contact", json=_VALID_PAYLOAD)

	assert resp.status_code == 200
	assert resp.json() == {"status": "received"}
	mock_smtp.assert_called_once()


def test_submit_contact_smtp_failure_returns_502() -> None:
	client = _build_client()

	with patch(
		"gbedu_api.routers.contact._send_smtp", side_effect=ConnectionRefusedError("SMTP down")
	):
		resp = client.post("/api/v1/contact", json=_VALID_PAYLOAD)

	assert resp.status_code == 502
	body = resp.json()
	assert body["detail"]["error_code"] == "EMAIL_ERROR"
	assert "gbedu.io" in body["detail"]["message"]


def test_submit_contact_missing_name_returns_422() -> None:
	client = _build_client()

	payload = {**_VALID_PAYLOAD}
	del payload["name"]

	resp = client.post("/api/v1/contact", json=payload)

	assert resp.status_code == 422


def test_submit_contact_invalid_email_returns_422() -> None:
	client = _build_client()

	payload = {**_VALID_PAYLOAD, "email": "not-an-email"}

	resp = client.post("/api/v1/contact", json=payload)

	assert resp.status_code == 422


def test_submit_contact_message_too_short_returns_422() -> None:
	client = _build_client()

	# message must be >= 10 characters
	payload = {**_VALID_PAYLOAD, "message": "short"}

	resp = client.post("/api/v1/contact", json=payload)

	assert resp.status_code == 422


def test_submit_contact_message_too_long_returns_422() -> None:
	client = _build_client()

	payload = {**_VALID_PAYLOAD, "message": "x" * 5001}

	resp = client.post("/api/v1/contact", json=payload)

	assert resp.status_code == 422


def test_submit_contact_subject_too_long_returns_422() -> None:
	client = _build_client()

	payload = {**_VALID_PAYLOAD, "subject": "s" * 301}

	resp = client.post("/api/v1/contact", json=payload)

	assert resp.status_code == 422


def test_submit_contact_extra_field_returns_422() -> None:
	client = _build_client()

	payload = {**_VALID_PAYLOAD, "phone": "+234-800-000-0000"}

	resp = client.post("/api/v1/contact", json=payload)

	assert resp.status_code == 422


def test_submit_contact_smtp_called_with_correct_fields() -> None:
	"""_send_smtp receives a ContactRequest with exactly the submitted values."""
	client = _build_client()

	captured = {}

	def _capture_smtp(body) -> None:
		captured["body"] = body

	with patch("gbedu_api.routers.contact._send_smtp", side_effect=_capture_smtp):
		resp = client.post("/api/v1/contact", json=_VALID_PAYLOAD)

	assert resp.status_code == 200
	assert captured["body"].name == "Funmilayo Okonkwo"
	assert captured["body"].email == "funmi@example.com"
	assert captured["body"].subject == "Collaboration request"


def test_submit_contact_empty_body_returns_422() -> None:
	client = _build_client()

	resp = client.post("/api/v1/contact", json={})

	assert resp.status_code == 422


def test_submit_contact_name_boundary_min_length_accepted() -> None:
	client = _build_client()

	payload = {**_VALID_PAYLOAD, "name": "A"}  # min_length=1

	with patch("gbedu_api.routers.contact._send_smtp"):
		resp = client.post("/api/v1/contact", json=payload)

	assert resp.status_code == 200
