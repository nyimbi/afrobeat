from __future__ import annotations

from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_api.config import RATE_LIMIT_AUTH, RATE_LIMIT_REGISTER, get_settings
from gbedu_api.deps import get_current_active_user, get_db, get_redis, limiter
from gbedu_api.services.auth_service import AuthService, TokenPair
from gbedu_api.services.email_service import EmailService
from gbedu_core.errors import GbeduError
from gbedu_core.models.user import User

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Request / Response schemas ─────────────────────────────────────────────────

class RegisterRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	email: EmailStr
	password: str = Field(min_length=8, max_length=128)
	full_name: str = Field(min_length=1, max_length=256)


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
@limiter.limit(RATE_LIMIT_REGISTER)
async def register(
	request: Request,
	body: RegisterRequest,
	background_tasks: BackgroundTasks,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> RegisterResponse:
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

	email_svc = EmailService(settings.email)
	background_tasks.add_task(email_svc.send_verify_email, user.email, user.full_name, verify_url)
	background_tasks.add_task(email_svc.send_welcome, user.email, user.full_name)

	return RegisterResponse(user=_user_summary(user), tokens=_token_response(tokens))


@router.post(
	"/login",
	response_model=TokenResponse,
	status_code=status.HTTP_200_OK,
	summary="Login with email and password",
)
@limiter.limit(RATE_LIMIT_AUTH)
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
@limiter.limit(RATE_LIMIT_AUTH)
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
@limiter.limit("5/hour")
async def forgot_password(
	request: Request,
	body: ForgotPasswordRequest,
	background_tasks: BackgroundTasks,
	db: Annotated[AsyncSession, Depends(get_db)],
	redis: Annotated[Redis, Depends(get_redis)],
) -> MessageResponse:
	svc = AuthService(db, redis)
	settings = get_settings()
	reset_token = await svc.create_password_reset_token(str(body.email))

	if reset_token:
		reset_url = f"{settings.frontend_url}/reset-password?token={reset_token}"
		from sqlalchemy import select
		from gbedu_core.models.user import User
		result = await db.execute(
			select(User).where(User.email == str(body.email).lower())
		)
		user = result.scalar_one_or_none()
		if user:
			email_svc = EmailService(settings.email)
			background_tasks.add_task(
				email_svc.send_password_reset, user.email, user.full_name, reset_url
			)

	# Always return the same response to prevent email enumeration
	return MessageResponse(message="If that email is registered, a reset link has been sent")


@router.post(
	"/reset-password",
	response_model=MessageResponse,
	status_code=status.HTTP_200_OK,
	summary="Reset password using token from email",
)
@limiter.limit(RATE_LIMIT_AUTH)
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
				detail={"error_code": "AUTHENTICATION_ERROR", "message": "Failed to fetch Google profile"},
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
