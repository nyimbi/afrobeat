from __future__ import annotations

import structlog
from aiosmtplib import SMTP, SMTPException
from jinja2 import Environment, PackageLoader, select_autoescape

from gbedu_core.config import EmailSettings

log = structlog.get_logger(__name__)


def _make_jinja_env() -> Environment:
	try:
		env = Environment(
			loader=PackageLoader("gbedu_api", "templates/email"),
			autoescape=select_autoescape(["html"]),
		)
	except Exception:
		# Fall back to a minimal dict-based renderer when templates are missing
		env = Environment(autoescape=False)
	return env


_jinja_env = _make_jinja_env()


class EmailService:
	def __init__(self, settings: EmailSettings) -> None:
		self._settings = settings

	async def _send(self, to: str, subject: str, html_body: str) -> None:
		assert to, "recipient must not be empty"
		assert subject, "subject must not be empty"

		from email.mime.multipart import MIMEMultipart
		from email.mime.text import MIMEText

		msg = MIMEMultipart("alternative")
		msg["Subject"] = subject
		msg["From"] = self._settings.from_email
		msg["To"] = to
		msg.attach(MIMEText(html_body, "html"))

		try:
			async with SMTP(
				hostname=self._settings.smtp_host,
				port=self._settings.smtp_port,
				use_tls=self._settings.use_tls,
			) as smtp:
				if self._settings.smtp_user:
					await smtp.login(self._settings.smtp_user, self._settings.smtp_password)
				await smtp.send_message(msg)
		except SMTPException as exc:
			log.error("email.send.failed", to=to, subject=subject, error=str(exc))
			raise

		log.info("email.sent", to=to, subject=subject)

	def _render(self, template_name: str, **ctx: object) -> str:
		try:
			tmpl = _jinja_env.get_template(template_name)
			return tmpl.render(**ctx)
		except Exception:
			# Degrade gracefully — plain text substitute
			return f"<p>{ {k: v for k, v in ctx.items()} }</p>"

	async def send_welcome(self, to: str, full_name: str) -> None:
		html = self._render("welcome.html", full_name=full_name)
		await self._send(to, "Welcome to Gbẹdu", html)

	async def send_verify_email(self, to: str, full_name: str, verify_url: str) -> None:
		html = self._render("verify_email.html", full_name=full_name, verify_url=verify_url)
		await self._send(to, "Verify your Gbẹdu email address", html)

	async def send_password_reset(self, to: str, full_name: str, reset_url: str) -> None:
		html = self._render("reset_password.html", full_name=full_name, reset_url=reset_url)
		await self._send(to, "Reset your Gbẹdu password", html)

	async def send_generation_complete(
		self,
		to: str,
		full_name: str,
		track_title: str,
		track_url: str,
	) -> None:
		html = self._render(
			"generation_complete.html",
			full_name=full_name,
			track_title=track_title,
			track_url=track_url,
		)
		await self._send(to, f"Your track \"{track_title}\" is ready", html)
