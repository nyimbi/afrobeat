from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from gbedu_core.errors import GbeduError
from gbedu_core.models.track import Language, SubGenre
from gbedu_core.models.user import User
from pydantic import BaseModel, ConfigDict, Field

from gbedu_api.config import RATE_LIMIT_FREE
from gbedu_api.deps import get_current_active_user, get_ml_client, limiter
from gbedu_api.services.ml_client import GenerationRequest, MLServiceClient

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/lyrics", tags=["lyrics"])


def _rate_limit[F: Callable[..., Any]](limit_value: str) -> Callable[[F], F]:
	return cast(Callable[[F], F], cast(Any, limiter).limit(limit_value))


class LyricDraftRequest(BaseModel):
	"""Lightweight lyric-only draft — no audio, no quota deduction."""

	model_config = ConfigDict(extra="forbid", populate_by_name=True)
	prompt: str = Field(min_length=10, max_length=2048)
	sub_genre: SubGenre = Field(validation_alias="subGenre")
	language: Language


class LyricDraftResponse(BaseModel):
	model_config = ConfigDict(extra="forbid", populate_by_name=True)
	verse1: str = Field(default="")
	prehook: str = Field(default="")
	hook: str = Field(default="")
	verse2: str = Field(default="")
	bridge: str = Field(default="")
	outro: str = Field(default="")
	full_lyrics: str = Field(alias="fullLyrics")
	language_used: str = Field(alias="languageUsed")
	fell_back_to_english: bool = Field(default=False, alias="fellBackToEnglish")
	structure_retries: int = Field(default=0, alias="structureRetries")
	language_disclosure: str | None = Field(default=None, alias="languageDisclosure")


@router.post(
	"/draft",
	response_model=LyricDraftResponse,
	status_code=status.HTTP_200_OK,
	summary="Draft lyrics only (no audio, no credit cost)",
)
@_rate_limit(RATE_LIMIT_FREE)
async def draft_lyrics(
	request: Request,
	body: LyricDraftRequest,
	user: Annotated[User, Depends(get_current_active_user)],
	ml: Annotated[MLServiceClient, Depends(get_ml_client)],
) -> LyricDraftResponse:
	# Deliberately no quota deduction and no verified-email gate: drafts are
	# seconds-cheap (no audio) and exploration should stay frictionless.
	# Abuse is bounded by the rate limiter.
	gen_request = GenerationRequest(
		prompt=body.prompt,
		sub_genre=body.sub_genre.value,
		language=body.language.value,
	)
	try:
		draft = await ml.draft_lyrics(gen_request)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())

	log.info("lyrics.drafted", user_id=user.id, language=body.language.value)
	return LyricDraftResponse(**draft)
