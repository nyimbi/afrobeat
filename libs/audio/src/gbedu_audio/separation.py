from __future__ import annotations

import asyncio
import time
from pathlib import Path

import structlog
import torch
from circuitbreaker import circuit
from opentelemetry import trace

from gbedu_audio._base import AudioFile, AudioProcessingError, ProcessingResult

log = structlog.get_logger(__name__)
_tracer = trace.get_tracer(__name__)

# Stem names produced by htdemucs_6s
_STEM_NAMES = ("drums", "bass", "other", "vocals", "guitar", "piano")


def _probe_audio_file(path: Path) -> AudioFile:  # pragma: no cover
	import soundfile as sf

	info = sf.info(str(path))
	return AudioFile(
		path=path,
		duration_seconds=float(info.duration),
		sample_rate=int(info.samplerate),
		channels=int(info.channels),
		format=info.format,
		size_bytes=path.stat().st_size,
	)


class StemSeparator:
	"""Async stem separator using Demucs htdemucs_6s (drums/bass/other/vocals/guitar/piano)."""

	def __init__(self) -> None:  # pragma: no cover
		self._model: object | None = None
		self._device: str = "cuda" if torch.cuda.is_available() else "cpu"
		self._model_name = "htdemucs_6s"

	async def _ensure_model(self) -> None:  # pragma: no cover
		if self._model is not None:
			return
		loop = asyncio.get_running_loop()
		self._model = await loop.run_in_executor(None, self._load_model_sync)

	def _load_model_sync(self) -> object:  # pragma: no cover
		from demucs.pretrained import get_model

		log.info("loading demucs model", model=self._model_name, device=self._device)
		model = get_model(self._model_name)
		model.to(self._device)  # type: ignore[attr-defined]
		model.eval()  # type: ignore[attr-defined]
		log.info("demucs model loaded", model=self._model_name, device=self._device)
		return model

	@circuit(failure_threshold=3, recovery_timeout=60)
	async def separate(  # pragma: no cover
		self,
		audio_path: Path,
		output_dir: Path,
	) -> dict[str, Path]:
		"""
		Separate audio into 6 stems. Returns mapping of stem name -> output WAV path.

		Circuit breaker: trips after 3 failures within 60 s.
		"""
		assert audio_path.is_file(), f"audio file not found: {audio_path}"
		output_dir.mkdir(parents=True, exist_ok=True)

		t0 = time.perf_counter()
		with _tracer.start_as_current_span("audio.separate_stems") as span:
			span.set_attribute("audio.path", str(audio_path))
			span.set_attribute("audio.model", self._model_name)
			span.set_attribute("audio.device", self._device)
			try:
				await self._ensure_model()
				loop = asyncio.get_running_loop()
				stem_paths = await loop.run_in_executor(
					None, self._separate_sync, audio_path, output_dir,
				)
				elapsed = time.perf_counter() - t0
				log.info(
					"stems separated",
					path=str(audio_path),
					stems=list(stem_paths.keys()),
					elapsed_s=elapsed,
				)
				return stem_paths
			except AudioProcessingError:
				raise
			except Exception as exc:
				raise AudioProcessingError(str(exc), stage="separate_stems") from exc

	def _separate_sync(self, audio_path: Path, output_dir: Path) -> dict[str, Path]:  # pragma: no cover
		import soundfile as sf
		import torchaudio

		from demucs.apply import apply_model
		from demucs.audio import convert_audio

		model = self._model  # already loaded

		# Load waveform and resample to model's expected rate
		waveform, sr = torchaudio.load(str(audio_path))
		waveform = convert_audio(waveform, sr, model.samplerate, model.audio_channels)  # type: ignore[attr-defined]
		# Add batch dimension: (1, channels, samples)
		waveform = waveform.unsqueeze(0).to(self._device)

		with torch.no_grad():
			sources = apply_model(model, waveform, device=self._device, progress=False)
		# sources shape: (batch, n_sources, channels, samples) — squeeze batch
		sources = sources[0]  # (n_sources, channels, samples)

		stem_paths: dict[str, Path] = {}
		track_name = audio_path.stem

		for idx, stem_name in enumerate(model.sources):  # type: ignore[attr-defined]
			stem_audio = sources[idx].cpu().float().numpy()  # (channels, samples)
			stem_audio = stem_audio.T  # (samples, channels) for soundfile

			out_path = output_dir / f"{track_name}_{stem_name}.wav"
			sf.write(
				str(out_path),
				stem_audio,
				model.samplerate,  # type: ignore[attr-defined]
				subtype="PCM_24",
			)
			stem_paths[stem_name] = out_path

		return stem_paths
