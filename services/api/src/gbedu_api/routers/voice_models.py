from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from gbedu_core._uuid7 import uuid7str
from gbedu_core.errors import GbeduError
from gbedu_core.models.user import SubscriptionTier, User
from gbedu_core.models.voice import VoiceArchetype, VoiceModel, VoiceModelStatus
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from gbedu_api.config import MAX_UPLOAD_SIZE_BYTES
from gbedu_api.deps import get_current_active_user, get_db, get_storage, require_tier
from gbedu_api.services.storage_service import StorageClient

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/voice-models", tags=["voice-models"])

_ALLOWED_AUDIO_TYPES = {
	"audio/mpeg",
	"audio/wav",
	"audio/flac",
	"audio/x-wav",
	"audio/ogg",
}


# ── Schemas ────────────────────────────────────────────────────────────────────


class VoiceModelResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	id: str
	name: str
	description: str | None
	archetype: str
	status: str
	is_preset: bool
	is_public: bool
	training_progress_percent: int
	error_message: str | None
	created_at: str


class UploadVoiceModelRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")
	name: str = Field(min_length=1, max_length=128)
	description: str | None = None


class DeleteVoiceModelResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")
	message: str


def _vm_response(vm: VoiceModel) -> VoiceModelResponse:
	return VoiceModelResponse(
		id=vm.id,
		name=vm.name,
		description=vm.description,
		archetype=vm.archetype.value,
		status=vm.status.value,
		is_preset=vm.is_preset,
		is_public=vm.is_public,
		training_progress_percent=vm.training_progress_percent,
		error_message=vm.error_message,
		created_at=vm.created_at.isoformat(),
	)


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
	"",
	response_model=list[VoiceModelResponse],
	status_code=status.HTTP_200_OK,
	summary="List preset voice archetypes and user's custom models",
)
async def list_voice_models(
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> list[VoiceModelResponse]:
	# System presets visible to all
	preset_result = await db.execute(
		select(VoiceModel)
		.where(
			VoiceModel.is_preset.is_(True),
			VoiceModel.status == VoiceModelStatus.ready,
			VoiceModel.deleted_at.is_(None),
		)
		.order_by(VoiceModel.name)
	)
	presets = list(preset_result.scalars().all())

	# User's own custom models
	custom_result = await db.execute(
		select(VoiceModel)
		.where(
			VoiceModel.user_id == user.id,
			VoiceModel.is_preset.is_(False),
			VoiceModel.deleted_at.is_(None),
		)
		.order_by(desc(VoiceModel.created_at))
	)
	custom = list(custom_result.scalars().all())

	return [_vm_response(vm) for vm in presets + custom]


@router.post(
	"/upload",
	response_model=VoiceModelResponse,
	status_code=status.HTTP_202_ACCEPTED,
	summary="Upload voice samples to train a custom RVC model (Pro+ only)",
)
async def upload_voice_sample(
	name: str,
	file: UploadFile,
	user: Annotated[User, Depends(require_tier(SubscriptionTier.pro))],
	db: Annotated[AsyncSession, Depends(get_db)],
	storage: Annotated[StorageClient, Depends(get_storage)],
	description: str | None = None,
) -> VoiceModelResponse:
	if file.content_type not in _ALLOWED_AUDIO_TYPES:
		raise HTTPException(
			status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
			detail={
				"error_code": "VALIDATION_ERROR",
				"message": f"Unsupported audio type {file.content_type}. Use MP3, WAV, FLAC, or OGG.",
			},
		)

	content = await file.read()
	if len(content) > MAX_UPLOAD_SIZE_BYTES:
		raise HTTPException(
			status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
			detail={
				"error_code": "VALIDATION_ERROR",
				"message": f"File exceeds {MAX_UPLOAD_SIZE_BYTES // 1024 // 1024}MB limit",
			},
		)

	voice_model_id = uuid7str()
	ext = (file.filename or "audio.wav").rsplit(".", 1)[-1].lower()
	key = f"voice-samples/{user.id}/{voice_model_id}/sample.{ext}"

	import tempfile
	from pathlib import Path

	with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
		tmp.write(content)
		tmp_path = Path(tmp.name)

	try:
		sample_url = await storage.upload_audio(tmp_path, key, content_type=file.content_type)
	except GbeduError as exc:
		raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
	finally:
		tmp_path.unlink(missing_ok=True)

	vm = VoiceModel(
		id=voice_model_id,
		user_id=user.id,
		name=name[:128],
		description=description,
		archetype=VoiceArchetype.custom,
		status=VoiceModelStatus.pending,
		is_preset=False,
		is_public=False,
		training_audio_urls=[sample_url],
	)
	db.add(vm)
	await db.flush()

	# Enqueue RVC training task
	try:
		from gbedu_api.worker_tasks import enqueue_voice_training

		enqueue_voice_training(vm.id)
	except Exception as exc:
		log.warning("voice_model.enqueue_failed", vm_id=vm.id, error=str(exc))

	log.info("voice_model.uploaded", vm_id=vm.id, user_id=user.id)
	return _vm_response(vm)


@router.get(
	"/{model_id}/status",
	response_model=VoiceModelResponse,
	status_code=status.HTTP_200_OK,
	summary="Get voice model training status",
)
async def get_voice_model_status(
	model_id: str,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> VoiceModelResponse:
	result = await db.execute(
		select(VoiceModel).where(
			VoiceModel.id == model_id,
			VoiceModel.deleted_at.is_(None),
		)
	)
	vm = result.scalar_one_or_none()

	if vm is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail={"error_code": "NOT_FOUND", "message": "Voice model not found"},
		)

	# Presets are public; custom models only visible to their owner
	if not vm.is_preset and vm.user_id != user.id:
		raise HTTPException(
			status_code=status.HTTP_403_FORBIDDEN,
			detail={
				"error_code": "AUTHORIZATION_ERROR",
				"message": "You do not own this voice model",
			},
		)

	return _vm_response(vm)


@router.delete(
	"/{model_id}",
	response_model=DeleteVoiceModelResponse,
	status_code=status.HTTP_200_OK,
	summary="Delete a custom voice model",
)
async def delete_voice_model(
	model_id: str,
	user: Annotated[User, Depends(get_current_active_user)],
	db: Annotated[AsyncSession, Depends(get_db)],
) -> DeleteVoiceModelResponse:
	result = await db.execute(
		select(VoiceModel).where(
			VoiceModel.id == model_id,
			VoiceModel.deleted_at.is_(None),
		)
	)
	vm = result.scalar_one_or_none()

	if vm is None:
		raise HTTPException(
			status_code=status.HTTP_404_NOT_FOUND,
			detail={"error_code": "NOT_FOUND", "message": "Voice model not found"},
		)

	if vm.is_preset:
		raise HTTPException(
			status_code=status.HTTP_403_FORBIDDEN,
			detail={"error_code": "AUTHORIZATION_ERROR", "message": "Cannot delete system presets"},
		)

	if vm.user_id != user.id:
		raise HTTPException(
			status_code=status.HTTP_403_FORBIDDEN,
			detail={
				"error_code": "AUTHORIZATION_ERROR",
				"message": "You do not own this voice model",
			},
		)

	await vm.delete(db)
	log.info("voice_model.deleted", model_id=model_id, user_id=user.id)
	return DeleteVoiceModelResponse(message="Voice model deleted")
