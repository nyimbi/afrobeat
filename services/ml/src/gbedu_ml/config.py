from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MLSettings(BaseSettings):
	model_config = SettingsConfigDict(
		env_prefix="GBEDU_ML_",
		env_file=".env",
		env_file_encoding="utf-8",
		extra="ignore",
	)

	# ── Auth ───────────────────────────────────────────────────────────────────
	API_KEY: str = Field(..., description="Internal service API key — required")

	# ── GPU ────────────────────────────────────────────────────────────────────
	GPU_DEVICE: str = Field(default="cuda", description="torch device string: cuda, cuda:0, mps, cpu")

	# ── Model cache dir ────────────────────────────────────────────────────────
	MODEL_CACHE_DIR: Path = Field(
		default=Path("/tmp/gbedu_model_cache"),
		description="HuggingFace cache root — mount a fast SSD here in production",
	)

	# ── HuggingFace model IDs ──────────────────────────────────────────────────
	ACE_STEP_MODEL_ID: str = Field(
		default="ACE-Step/ACE-Step",
		description="HuggingFace repo ID for ACE-Step 1.5",
	)
	ACE_STEP_LORA_ID: str | None = Field(
		default=None,
		description="Optional LoRA adapter repo ID for Afrobeats fine-tune",
	)
	STABLE_AUDIO_MODEL_ID: str = Field(
		default="stabilityai/stable-audio-open-1.0",
		description="HuggingFace repo ID for Stable Audio 3.0 Medium",
	)
	YUE_MODEL_ID: str = Field(
		default="m-a-p/YuE-s1-anneal-en-cot",
		description="HuggingFace repo ID for YuE 7B",
	)
	LLAMA_MODEL_ID: str = Field(
		default="meta-llama/Meta-Llama-3-8B-Instruct",
		description="HuggingFace repo ID for Llama-3 8B Instruct (lyric generation)",
	)
	LLAMA_MAX_NEW_TOKENS: int = Field(
		default=1024,
		ge=64,
		le=2048,
		description="Hard cap on tokens generated per Llama-3 call — prevents runaway generation consuming VRAM",
	)

	# ── RVC voice conversion ───────────────────────────────────────────────────
	RVC_MODELS_DIR: Path = Field(
		default=Path("/tmp/gbedu_rvc_models"),
		description="Directory containing preset RVC v2 .pth voice model files",
	)

	# ── Concurrency / timeouts ─────────────────────────────────────────────────
	MAX_CONCURRENT_GENERATIONS: int = Field(
		default=4,
		ge=1,
		le=32,
		description="Semaphore limit for parallel generation requests",
	)
	GENERATION_TIMEOUT_SECONDS: int = Field(
		default=300,
		ge=30,
		le=600,
		description="Hard wall-clock timeout for a single generation pipeline run",
	)

	# ── Observability ──────────────────────────────────────────────────────────
	OTLP_ENDPOINT: str = Field(
		default="",
		description="OTLP gRPC endpoint, e.g. http://otel-collector:4317. Empty → no export.",
	)

	# ── Redis (progress pub/sub) ───────────────────────────────────────────────
	REDIS_URL: str = Field(
		default="redis://localhost:6379/0",
		description="Redis connection URL for progress pub/sub",
	)

	# ── Output storage ─────────────────────────────────────────────────────────
	OUTPUT_DIR: Path = Field(
		default=Path("/tmp/gbedu_output"),
		description="Directory where generated WAV files are written before upload",
	)

	# ── HuggingFace auth ───────────────────────────────────────────────────────
	HF_TOKEN: str | None = Field(
		default=None,
		description="HuggingFace access token for gated models (Llama etc.)",
	)

	def model_post_init(self, __context: object) -> None:
		self.MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
		self.RVC_MODELS_DIR.mkdir(parents=True, exist_ok=True)
		self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


settings = MLSettings()  # type: ignore[call-arg]
