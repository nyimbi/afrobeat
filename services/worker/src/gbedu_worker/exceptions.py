from __future__ import annotations

"""Worker-local exception hierarchy."""


class WorkerError(Exception):
	"""Base class for all gbedu_worker exceptions."""


class MLServiceError(WorkerError):
	"""ML service returned a non-2xx response or timed out."""


class UploadError(WorkerError):
	"""R2 object upload failed after all retries."""


class DistributionError(WorkerError):
	"""DSP distribution API call failed."""


class PipelineStateError(WorkerError):
	"""Unexpected state encountered during pipeline execution."""
