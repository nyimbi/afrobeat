from __future__ import annotations

import asyncio
import subprocess
import uuid
from pathlib import Path
from typing import Any

import structlog

from gbedu_ml.config import settings
from gbedu_ml.models.base import BaseMusGen

log = structlog.get_logger(__name__)

# audio.cpp session options are fixed per model build; request options vary per call.
_COT_CHOICES = ("full", "melody", "off")


class YuE2Model(BaseMusGen):
	"""YuE2-3B GGUF via the audio.cpp runtime (audiocpp_cli subprocess).

	Second slot in the generation chain. audio.cpp is a self-contained C++
	inference runtime: no Python model deps, CUDA or CPU backends, WAV output.
	Unlike the diffusion backends, YuE2 consumes style + lyrics separately and
	derives song length from lyric structure — no duration parameter. Output
	is trimmed to the requested duration after the fact.
	"""

	def __init__(self) -> None:
		super().__init__()
		self._bin: Path = settings.YUE2_AUDIOCPP_BIN
		self._local_dir: Path | None = None

	@property
	def model_id(self) -> str:
		return settings.YUE2_MODEL_ID

	async def load(self) -> None:
		# Weights are downloaded lazily on first generate() (audio.cpp resolves
		# HF repo ids directly). Loading is therefore just a binary probe.
		loop = asyncio.get_event_loop()
		await loop.run_in_executor(None, self._load_sync)

	def _load_sync(self) -> None:
		log.info(
			"yue2.load.start",
			model=self.model_id,
			bin=str(self._bin),
			model_gguf=settings.YUE2_MODEL_GGUF,
			vae_gguf=settings.YUE2_VAE_GGUF,
		)

		if not self._bin.is_file():
			raise RuntimeError(
				f"audiocpp_cli not found at {self._bin} — "
				"install audio.cpp (dev branch) or point YUE2_AUDIOCPP_BIN at it"
			)
		if "cuda" not in settings.GPU_DEVICE:
			log.warning(
				"yue2.cpu_backend",
				device=settings.GPU_DEVICE,
				hint="GGUF runs on CPU but slowly; expect RTF >> 1",
			)

		self._is_loaded = True
		log.info("yue2.load.done", model=self.model_id)

	async def generate(self, prompt: str, duration_seconds: int, **kwargs: Any) -> Path:
		assert self._is_loaded, "model not loaded — call load() first"
		assert prompt, "prompt must not be empty"
		assert duration_seconds > 0, "duration_seconds must be positive"

		loop = asyncio.get_event_loop()
		return await loop.run_in_executor(
			None, self._generate_sync, prompt, duration_seconds, kwargs
		)

	def _generate_sync(self, prompt: str, duration_seconds: int, kwargs: dict[str, Any]) -> Path:
		assert self._is_loaded, "model not loaded — call load() first"
		assert prompt, "prompt must not be empty"
		assert duration_seconds > 0, "duration_seconds must be positive"
		out_path = settings.OUTPUT_DIR / f"yue2_{uuid.uuid4().hex}.wav"
		cot = kwargs.get("cot", settings.YUE2_COT)
		assert cot in _COT_CHOICES, f"cot must be one of {_COT_CHOICES}, got {cot!r}"

		style = kwargs.get("style_tags") or prompt
		lyrics = kwargs.get("lyrics")

		cmd = [
			str(self._bin),
			"--task",
			"gen",
			"--family",
			"yue2",
			"--model",
			self.model_id,
			"--backend",
			"cuda" if "cuda" in settings.GPU_DEVICE else "cpu",
			"--threads",
			str(settings.YUE2_THREADS),
			"--text",
			lyrics or prompt,
			"--request-option",
			f"style={style}",
			"--request-option",
			f"cot={cot}",
			"--request-option",
			f"num_inference_steps={kwargs.get('num_inference_steps', settings.YUE2_NUM_INFERENCE_STEPS)}",
			"--request-option",
			f"seed={kwargs.get('seed', 0)}",
			"--session-option",
			f"yue2.model_gguf={settings.YUE2_MODEL_GGUF}",
			"--session-option",
			f"yue2.vae_gguf={settings.YUE2_VAE_GGUF}",
			"--out",
			str(out_path),
			"--log",
		]

		if abc_score := kwargs.get("abc"):
			cmd.extend(["--request-option", f"abc_file={abc_score}"])

		log.info(
			"yue2.generate.start",
			model=self.model_id,
			cot=cot,
			has_lyrics=lyrics is not None,
			has_abc=bool(abc_score),
		)

		try:
			subprocess.run(
				cmd,
				check=True,
				capture_output=True,
				text=True,
				timeout=settings.YUE2_TIMEOUT_SECONDS,
			)
		except subprocess.TimeoutExpired as exc:
			raise RuntimeError(
				f"YuE2 generation exceeded {settings.YUE2_TIMEOUT_SECONDS}s timeout"
			) from exc
		except subprocess.CalledProcessError as exc:
			raise RuntimeError(
				f"audiocpp_cli failed (exit {exc.returncode}): {exc.stderr[-2000:] if exc.stderr else 'no stderr'}"
			) from exc

		if not out_path.is_file():
			raise RuntimeError(f"audiocpp_cli did not produce output at {out_path}")

		self._trim_to_duration(out_path, duration_seconds)

		log.info("yue2.generated", path=str(out_path), duration_seconds=duration_seconds)
		return out_path

	def _trim_to_duration(self, wav_path: Path, duration_seconds: int) -> None:
		"""Trim/pad the generated WAV to the requested duration in-place."""
		if not wav_path.is_file():
			return
		try:
			trimmed = wav_path.with_suffix(".trim.wav")
			subprocess.run(
				[
					"ffmpeg",
					"-y",
					"-loglevel",
					"error",
					"-i",
					str(wav_path),
					"-t",
					str(duration_seconds),
					"-c:a",
					"pcm_s16le",
					str(trimmed),
				],
				check=True,
				capture_output=True,
			)
			trimmed.replace(wav_path)
		except (subprocess.CalledProcessError, FileNotFoundError) as exc:
			log.warning("yue2.trim.failed", error=str(exc))

	async def unload(self) -> None:
		self._local_dir = None
		await super().unload()
