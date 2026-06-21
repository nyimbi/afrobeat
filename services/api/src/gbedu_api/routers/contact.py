from __future__ import annotations

"""Contact form endpoint.

Rate of incoming messages is low enough that synchronous SMTP in a thread
pool is sufficient. No Celery task needed — inline send keeps the retry path
simple (the client retries on 502 rather than us needing a task queue).
"""

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog
from fastapi import APIRouter, HTTPException, status
from gbedu_core.config import EmailSettings
from pydantic import BaseModel, ConfigDict, EmailStr, Field

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/contact", tags=["contact"])

_email_settings = EmailSettings()


class ContactRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	name: str = Field(min_length=1, max_length=200)
	email: EmailStr
	subject: str = Field(min_length=1, max_length=300)
	message: str = Field(min_length=10, max_length=5000)


@router.post(
	"",
	status_code=status.HTTP_200_OK,
	summary="Submit a contact form message",
)
async def submit_contact(body: ContactRequest) -> dict[str, str]:
	"""Validate and forward a contact form submission by email.

	Returns 200 immediately once the SMTP send succeeds. On SMTP failure,
	returns 502 so the client knows to retry — the message has NOT been lost
	since it was never queued; the caller should display a retry prompt.
	"""
	assert body.name, "name required"
	assert body.email, "email required"
	assert body.subject, "subject required"
	assert body.message, "message required"

	try:
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(None, _send_smtp, body)
	except Exception as exc:
		log.error("contact.send_failed", exc_type=type(exc).__name__, exc_msg=str(exc))
		raise HTTPException(
			status_code=status.HTTP_502_BAD_GATEWAY,
			detail={
				"error_code": "EMAIL_ERROR",
				"message": "Failed to deliver your message. Please try again or email support@gbedu.io directly.",
			},
		)

	log.info("contact.received", sender_email=body.email, subject=body.subject)
	return {"status": "received"}


def _send_smtp(body: ContactRequest) -> None:  # pragma: no cover
	safe_message = body.message.replace("\n", "<br>")

	html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;color:#333;max-width:600px;margin:0 auto;padding:24px;">
  <h2 style="color:#D4AF37;">New contact form submission</h2>
  <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
    <tr><td style="padding:6px 0;font-weight:bold;width:80px;">From:</td>
        <td>{body.name} &lt;{body.email}&gt;</td></tr>
    <tr><td style="padding:6px 0;font-weight:bold;">Subject:</td>
        <td>{body.subject}</td></tr>
  </table>
  <hr style="border:none;border-top:1px solid #eee;margin:16px 0;">
  <p style="white-space:pre-wrap;">{safe_message}</p>
</body>
</html>
"""

	msg = MIMEMultipart("alternative")
	msg["Subject"] = f"[Gbẹdu Contact] {body.subject}"
	msg["From"] = _email_settings.from_email
	msg["To"] = _email_settings.from_email
	msg["Reply-To"] = body.email
	msg.attach(MIMEText(html, "html"))

	with smtplib.SMTP(_email_settings.smtp_host, _email_settings.smtp_port) as server:
		if _email_settings.use_tls:
			server.starttls()
		if _email_settings.smtp_user:
			server.login(_email_settings.smtp_user, _email_settings.smtp_password)
		server.sendmail(_email_settings.from_email, _email_settings.from_email, msg.as_string())
