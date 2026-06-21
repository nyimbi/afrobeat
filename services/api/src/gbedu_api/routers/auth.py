from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, cast

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from gbedu_core.errors import GbeduError
from gbedu_core.models.user import User
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_api.config import RATE_LIMIT_LOGIN, RATE_LIMIT_REFRESH, RATE_LIMIT_REGISTER, get_settings
from gbedu_api.deps import get_db, get_redis, limiter
from gbedu_api.services.auth_service import AuthService, TokenPair
from gbedu_api.worker_tasks import (
	enqueue_password_reset_email,
	enqueue_verify_email,
	enqueue_welcome_email,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _rate_limit[F: Callable[..., Any]](limit_value: str) -> Callable[[F], F]:
	return cast(Callable[[F], F], cast(Any, limiter).limit(limit_value))


# ── Request / Response schemas ─────────────────────────────────────────────────


class RegisterRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	email: EmailStr
	password: str = Field(min_length=8, max_length=128)
	full_name: str = Field(min_length=1, max_length=256)
	# FMEA S05: honeypot — invisible to real users (hidden via CSS), filled only by bots.
	# Named 'website' to look like a plausible form field. Must remain empty.
	website: str | None = Field(default=None, exclude=True)


class LoginRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	email: EmailStr
	password: str = Field(min_length=1)


class RefreshRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	refresh_token: str


class LogoutRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	refresh_token: str


class VerifyEmailRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	token: str


class ForgotPasswordRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	email: EmailStr


class ResetPasswordRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	token: str
	new_password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	access_token: str
	refresh_token: str
	token_type: str


class UserSummary(BaseModel):
	model_config = ConfigDict(extra="forbid")
	id: str
	email: str
	full_name: str
	is_verified: bool
	subscription_tier: str


class RegisterResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	user: UserSummary
	tokens: TokenResponse


class MessageResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	message: str


def _token_response(pair: TokenPair) -> TokenResponse:
	return TokenResponse(
		access_token=pair.access_token,
		refresh_token=pair.refresh_token,
		token_type=pair.token_type,
	)


def _user_summary(user: User) -> UserSummary:
	return UserSummary(
		id=user.id,
		email=user.email,
		full_name=user.full_name,
		is_verified=user.is_verified,
		subscription_tier=user.subscription_tier.value,
	)


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.post(
	"/register",
	response_model=RegisterResponse,
	status_code=status.HTTP_201_CREATED,
	summary="Register a new user account",
)
@_rate_limit(RATE_LIMIT_REGISTER)
async def register(
	request: Request,
	body: RegisterRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> RegisterResponse | JSONResponse:
	# FMEA S05: honeypot check — silently swallow bot registrations without
	# creating an account. Returning 201 means the bot thinks it succeeded and
	# won't retry or enumerate errors; legitimate clients never fill 'website'.
	if body.website:
		log.warning("auth.register.honeypot_triggered", email_prefix=str(body.email)[:8])
		return JSONResponse(status_code=201, content={"user": {}, "tokens": {}})

	svc = AuthService(db, redis)
	try:
		user, tokens = await svc.register(
			email=str(body.email),
			password=body.password,
			full_name=body.full_name,
		)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	verify_token = await svc.create_email_verification_token(user.id)
	settings = get_settings()
	verify_url = f"{settings.frontend_url}/verify-email?token={verify_token}"

	# Queue via Celery — durable, retryable, idempotent (24 h dedup key in Redis)
	enqueue_verify_email(user.id, verify_url)
	enqueue_welcome_email(user.id)

	return RegisterResponse(user=_user_summary(user), tokens=_token_response(tokens))


@router.post(
	"/login",
	response_model=TokenResponse,
	status_code=status.HTTP_200_OK,
	summary="Login with email and password",
)
@_rate_limit(RATE_LIMIT_LOGIN)
async def login(
	request: Request,
	body: LoginRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> TokenResponse:
	svc = AuthService(db, redis)
	try:
		_, tokens = await svc.login(str(body.email), body.password)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
	return _token_response(tokens)


@router.post(
	"/refresh",
	response_model=TokenResponse,
	status_code=status.HTTP_200_OK,
	summary="Exchange refresh token for a new access token",
)
@_rate_limit(RATE_LIMIT_REFRESH)
async def refresh_token(
	request: Request,
	body: RefreshRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> TokenResponse:
	svc = AuthService(db, redis)
	try:
		tokens = await svc.refresh(body.refresh_token)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
	return _token_response(tokens)


@router.post(
	"/logout",
	response_model=MessageResponse,
	status_code=status.HTTP_200_OK,
	summary="Invalidate refresh token",
)
async def logout(
	body: LogoutRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> MessageResponse:
	svc = AuthService(db, redis)
	await svc.logout(body.refresh_token)
	return MessageResponse(message="Logged out successfully")


@router.post(
	"/verify-email",
	response_model=MessageResponse,
	status_code=status.HTTP_200_OK,
	summary="Verify email address with token",
)
async def verify_email(
	body: VerifyEmailRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> MessageResponse:
	svc = AuthService(db, redis)
	try:
		await svc.verify_email(body.token)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
	return MessageResponse(message="Email verified successfully")


@router.post(
	"/forgot-password",
	response_model=MessageResponse,
	status_code=status.HTTP_200_OK,
	summary="Request a password reset email",
)
@_rate_limit("5/hour")
async def forgot_password(
	request: Request,
	body: ForgotPasswordRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> MessageResponse:
	svc = AuthService(db, redis)
	settings = get_settings()
	reset_token = await svc.create_password_reset_token(str(body.email))

	if reset_token:
		reset_url = f"{settings.frontend_url}/reset-password?token={reset_token}"
		from sqlalchemy import select

		result = await db.execute(select(User).where(User.email == str(body.email).lower()))
		user = result.scalar_one_or_none()
		if user:
			enqueue_password_reset_email(user.id, reset_url)

	# Always return the same response to prevent email enumeration
	return MessageResponse(message="If that email is registered, a reset link has been sent")


@router.post(
	"/reset-password",
	response_model=MessageResponse,
	status_code=status.HTTP_200_OK,
	summary="Reset password using token from email",
)
@_rate_limit(RATE_LIMIT_LOGIN)
async def reset_password(
	request: Request,
	body: ResetPasswordRequest,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> MessageResponse:
	svc = AuthService(db, redis)
	try:
		await svc.reset_password(body.token, body.new_password)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
	return MessageResponse(message="Password reset successfully")


@router.get(
	"/google",
	status_code=status.HTTP_302_FOUND,
	summary="Redirect to Google OAuth consent screen",
	include_in_schema=True,
)
async def google_oauth_start() -> RedirectResponse:
	settings = get_settings()
	params = {
		"client_id": settings.jwt.google_client_id,
		"redirect_uri": f"{settings.frontend_url}/api/v1/auth/google/callback",
		"response_type": "code",
		"scope": "openid email profile",
		"access_type": "offline",
	}
	from urllib.parse import urlencode

	url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
	return RedirectResponse(url=url)


@router.get(
	"/google/callback",
	response_model=TokenResponse,
	status_code=status.HTTP_200_OK,
	summary="Handle Google OAuth callback",
)
async def google_oauth_callback(
	code: str,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> TokenResponse:
	settings = get_settings()

	async with httpx.AsyncClient() as http:
		token_resp = await http.post(
			"https://oauth2.googleapis.com/token",
			data={
				"code": code,
				"client_id": settings.jwt.google_client_id,
				"client_secret": settings.jwt.google_client_secret,
				"redirect_uri": f"{settings.frontend_url}/api/v1/auth/google/callback",
				"grant_type": "authorization_code",
			},
		)
		if token_resp.status_code != 200:
			raise HTTPException(
				status_code=status.HTTP_400_BAD_REQUEST,
				detail={"error_code": "AUTHENTICATION_ERROR", "message": "Google OAuth failed"},
			)
		google_tokens = token_resp.json()

		userinfo_resp = await http.get(
			"https://www.googleapis.com/oauth2/v3/userinfo",
			headers={"Authorization": f"Bearer {google_tokens['access_token']}"},
		)
		if userinfo_resp.status_code != 200:
			raise HTTPException(
				status_code=status.HTTP_400_BAD_REQUEST,
				detail={
					"error_code": "AUTHENTICATION_ERROR",
					"message": "Failed to fetch Google profile",
				},
			)
		userinfo = userinfo_resp.json()

	svc = AuthService(db, redis)
	try:
		_, tokens = await svc.oauth_callback(
			provider="google",
			provider_id=userinfo["sub"],
			email=userinfo["email"],
			full_name=userinfo.get("name", userinfo["email"]),
			avatar_url=userinfo.get("picture"),
		)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	return _token_response(tokens)
