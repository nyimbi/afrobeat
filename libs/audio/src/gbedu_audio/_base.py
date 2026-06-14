from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AudioFile:
	path: Path
	duration_seconds: float
	sample_rate: int
	channels: int
	format: str
	size_bytes: int


class AudioProcessingError(Exception):
	"""Raised when an audio processing stage fails."""

	def __init__(self, message: str, *, stage: str) -> None:
		super().__init__(message)
		self.message = message
		self.stage = stage

	def __repr__(self) -> str:
		return f"AudioProcessingError(stage={self.stage!r}, message={self.message!r})"


@dataclass
class ProcessingResult:
	input: AudioFile
	output: AudioFile
	processing_time_seconds: float
	metadata: dict = field(default_factory=dict)
