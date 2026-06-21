from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import structlog
from gbedu_core.errors import GenerationError
from gbedu_core.schemas import GenerationRequest
from pydantic import BaseModel, ConfigDict, Field

from gbedu_ml.config import settings

if TYPE_CHECKING:
	from gbedu_ml.inference.lyric_generator import LyricGenerator, LyricResult
	from gbedu_ml.inference.music_generator import MusicGenerationResult, MusicGenerator
	from gbedu_ml.inference.vocal_synthesizer import VocalSynthesizer

log = structlog.get_logger(__name__)

_PIPELINE_TIMEOUT_SECONDS = settings.GENERATION_TIMEOUT_SECONDS


class GenerationPipelineResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	job_id: str
	final_audio_path: Path
	instrumental_path: Path
	vocal_path: Path | None = None
	lyrics_result: LyricResult | None = None
	music_result: MusicGenerationResult
	duration_seconds: int
	elapsed_seconds: float
	metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationPipeline:
	"""Full end-to-end Afrobeats generation pipeline.

	Steps (with partial parallelism):
	  1. Kick off music generation and lyric generation concurrently.
	  2. Once music is done, synthesize vocals if a voice_model_id is present.
	  3. Mix instrumental + vocals (pydub).
	  4. Publish progress updates to Redis pub/sub throughout.

	Hard timeout: settings.GENERATION_TIMEOUT_SECONDS.
	"""

	def __init__(
		self,
		music_gen: MusicGenerator,
		lyric_gen: LyricGenerator,
		vocal_synth: VocalSynthesizer,
	) -> None:
		self._music_gen = music_gen
		self._lyric_gen = lyric_gen
		self._vocal_synth = vocal_synth
		self._redis: Any = None

	async def _get_redis(self) -> Any:
		if self._redis is None:
			import redis.asyncio as aioredis  # type: ignore[import]

			self._redis = cast(Any, aioredis).from_url(settings.REDIS_URL, decode_responses=True)
		return self._redis

	async def _publish_progress(self, job_id: str, percent: int, stage: str) -> None:
		try:
			r = await self._get_redis()
			payload = json.dumps({"job_id": job_id, "progress_percent": percent, "stage": stage})
			await r.publish(f"job:{job_id}:progress", payload)
			log.info("pipeline.progress", job_id=job_id, percent=percent, stage=stage)
		except Exception as exc:
			# Progress pub/sub failure must never abort the generation
			log.warning("pipeline.progress.publish_failed", job_id=job_id, error=str(exc))

	async def run(self, request: GenerationRequest, job_id: str) -> GenerationPipelineResult:
		assert request.prompt, "request.prompt must not be empty"
		assert job_id, "job_id must not be empty"

		t0 = time.perf_counter()

		try:
			result = await asyncio.wait_for(
				self._run_inner(request, job_id, t0),
				timeout=_PIPELINE_TIMEOUT_SECONDS,
			)
		except TimeoutError:
			elapsed = time.perf_counter() - t0
			log.error(
				"pipeline.timeout",
				job_id=job_id,
				elapsed_seconds=round(elapsed, 1),
				timeout=_PIPELINE_TIMEOUT_SECONDS,
			)
			await self._publish_progress(job_id, -1, "timeout")
			raise GenerationError(
				f"Generation pipeline timed out after {_PIPELINE_TIMEOUT_SECONDS}s",
				job_id=job_id,
			)

		return result

	async def _run_inner(  # pragma: no cover
		self,
		request: GenerationRequest,
		job_id: str,
		t0: float,
	) -> GenerationPipelineResult:

		await self._publish_progress(job_id, 5, "starting")

		# ── Step 1: Music + lyrics in parallel ────────────────────────────────
		await self._publish_progress(job_id, 10, "generating_music_and_lyrics")

		music_task = asyncio.create_task(self._music_gen.generate(request))
		lyrics_task = asyncio.create_task(self._generate_lyrics_safe(request))

		music_result, lyric_result = await asyncio.gather(music_task, lyrics_task)

		await self._publish_progress(job_id, 60, "music_done")
		log.info(
			"pipeline.music.done",
			job_id=job_id,
			model=music_result.model_used,
			path=str(music_result.audio_path),
		)

		# ── Step 2: Vocal synthesis (optional) ────────────────────────────────
		vocal_path: Path | None = None

		if request.voice_model_id and self._vocal_synth.is_loaded and lyric_result is not None:
			await self._publish_progress(job_id, 65, "synthesizing_vocals")
			lyrics_text_path = await self._write_lyrics_file(job_id, lyric_result)
			try:
				vocal_path = await self._vocal_synth.synthesize(
					lyrics_path=lyrics_text_path,
					melody_path=music_result.audio_path,
					voice_model_id=request.voice_model_id,
				)
				await self._publish_progress(job_id, 80, "vocals_done")
			except Exception as exc:
				log.warning(
					"pipeline.vocal_synth.failed",
					job_id=job_id,
					error=str(exc),
				)
				# Non-fatal: deliver instrumental-only track

		# ── Step 3: Mix ────────────────────────────────────────────────────────
		await self._publish_progress(job_id, 85, "mixing")

		if vocal_path is not None:
			final_path = await self._mix(
				instrumental_path=music_result.audio_path,
				vocal_path=vocal_path,
				job_id=job_id,
			)
		else:
			final_path = music_result.audio_path

		await self._publish_progress(job_id, 95, "finalising")

		elapsed = time.perf_counter() - t0
		await self._publish_progress(job_id, 100, "done")

		log.info(
			"pipeline.done",
			job_id=job_id,
			elapsed_seconds=round(elapsed, 1),
			final_path=str(final_path),
		)

		return GenerationPipelineResult(
			job_id=job_id,
			final_audio_path=final_path,
			instrumental_path=music_result.audio_path,
			vocal_path=vocal_path,
			lyrics_result=lyric_result,
			music_result=music_result,
			duration_seconds=request.duration_seconds,
			elapsed_seconds=round(elapsed, 2),
			metadata={
				"model_used": music_result.model_used,
				"prompt_used": music_result.prompt_used,
				"has_vocals": vocal_path is not None,
				"language": request.language.value,
				"sub_genre": request.sub_genre.value,
			},
		)

	async def _generate_lyrics_safe(
		self, request: GenerationRequest
	) -> LyricResult | None:  # pragma: no cover
		if not self._lyric_gen.is_loaded:
			log.warning("pipeline.lyric_gen.not_loaded")
			return None
		try:
			return await self._lyric_gen.generate(request)
		except Exception as exc:
			log.warning("pipeline.lyric_gen.failed", error=str(exc))
			return None

	async def _write_lyrics_file(
		self, job_id: str, lyric_result: LyricResult
	) -> Path:  # pragma: no cover
		path = settings.OUTPUT_DIR / f"lyrics_{job_id}.txt"
		loop = asyncio.get_event_loop()

		def _write() -> None:
			path.write_text(lyric_result.full_lyrics, encoding="utf-8")

		await loop.run_in_executor(None, _write)
		return path

	async def _mix(  # pragma: no cover
		self,
		instrumental_path: Path,
		vocal_path: Path,
		job_id: str,
	) -> Path:
		loop = asyncio.get_event_loop()
		out_path = settings.OUTPUT_DIR / f"mix_{job_id}.wav"
		await loop.run_in_executor(None, self._mix_sync, instrumental_path, vocal_path, out_path)
		return out_path

	def _mix_sync(
		self, instrumental_path: Path, vocal_path: Path, out_path: Path
	) -> None:  # pragma: no cover
		from pydub import AudioSegment  # type: ignore[import]

		audio_segment = cast(Any, AudioSegment)
		instrumental = audio_segment.from_wav(str(instrumental_path))
		vocals = audio_segment.from_wav(str(vocal_path))

		# Normalise lengths — truncate the longer to the shorter
		min_len_ms = min(len(instrumental), len(vocals))
		instrumental = instrumental[:min_len_ms]
		vocals = vocals[:min_len_ms]

		# Vocals sit -3 dB above the instrumental
		vocals_adjusted = vocals - 3

		mixed = instrumental.overlay(vocals_adjusted)
		mixed.export(str(out_path), format="wav")

		log.info("pipeline.mix.done", out=str(out_path), duration_ms=len(mixed))
