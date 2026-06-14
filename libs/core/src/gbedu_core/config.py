from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
	model_config = SettingsConfigDict(extra="ignore")

	url: str = Field(alias="DATABASE_URL", default="postgresql+asyncpg://gbedu:gbedu@localhost:5432/gbedu")
	pool_size: int = Field(default=20)
	max_overflow: int = Field(default=40)
	pool_pre_ping: bool = Field(default=True)
	pool_recycle: int = Field(default=3600)
	echo: bool = Field(default=False)


class RedisSettings(BaseSettings):
	model_config = SettingsConfigDict(extra="ignore")

	url: str = Field(alias="REDIS_URL", default="redis://localhost:6379/0")


class StorageSettings(BaseSettings):
	model_config = SettingsConfigDict(extra="ignore")

	r2_account_id: str = Field(alias="R2_ACCOUNT_ID", default="")
	r2_access_key_id: str = Field(alias="R2_ACCESS_KEY_ID", default="")
	r2_secret_access_key: str = Field(alias="R2_SECRET_ACCESS_KEY", default="")
	r2_bucket_name: str = Field(alias="R2_BUCKET_NAME", default="gbedu-audio")
	r2_public_url: str = Field(alias="R2_PUBLIC_URL", default="")

	@property
	def r2_endpoint_url(self) -> str:
		return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"


class StripeSettings(BaseSettings):
	model_config = SettingsConfigDict(extra="ignore")

	secret_key: str = Field(alias="STRIPE_SECRET_KEY", default="")
	webhook_secret: str = Field(alias="STRIPE_WEBHOOK_SECRET", default="")
	price_id_creator: str = Field(alias="STRIPE_PRICE_ID_CREATOR", default="")
	price_id_pro: str = Field(alias="STRIPE_PRICE_ID_PRO", default="")
	price_id_label: str = Field(alias="STRIPE_PRICE_ID_LABEL", default="")


class PaystackSettings(BaseSettings):
	model_config = SettingsConfigDict(extra="ignore")

	secret_key: str = Field(alias="PAYSTACK_SECRET_KEY", default="")
	public_key: str = Field(alias="PAYSTACK_PUBLIC_KEY", default="")

	@property
	def base_url(self) -> str:
		return "https://api.paystack.co"


class JWTSettings(BaseSettings):
	model_config = SettingsConfigDict(extra="ignore")

	secret_key: str = Field(alias="JWT_SECRET_KEY", default="change-this-in-production")
	algorithm: str = Field(alias="JWT_ALGORITHM", default="HS256")
	access_token_expire_minutes: int = Field(alias="ACCESS_TOKEN_EXPIRE_MINUTES", default=30)
	refresh_token_expire_days: int = Field(alias="REFRESH_TOKEN_EXPIRE_DAYS", default=30)

	google_client_id: str = Field(alias="GOOGLE_CLIENT_ID", default="")
	google_client_secret: str = Field(alias="GOOGLE_CLIENT_SECRET", default="")


class MLSettings(BaseSettings):
	model_config = SettingsConfigDict(extra="ignore")

	service_url: str = Field(alias="ML_SERVICE_URL", default="http://localhost:8001")
	service_api_key: str = Field(alias="ML_SERVICE_API_KEY", default="")
	gpu_device: str = Field(alias="GPU_DEVICE", default="cuda")
	# Request timeout in seconds for long-running inference
	inference_timeout: int = Field(default=300)
	# Circuit breaker: how many failures before opening
	circuit_failure_threshold: int = Field(default=5)
	circuit_recovery_timeout: int = Field(default=60)


class CelerySettings(BaseSettings):
	model_config = SettingsConfigDict(extra="ignore")

	broker_url: str = Field(alias="CELERY_BROKER_URL", default="redis://localhost:6379/1")
	result_backend: str = Field(alias="CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")
	task_serializer: str = Field(default="json")
	result_serializer: str = Field(default="json")
	accept_content: list[str] = Field(default_factory=lambda: ["json"])
	task_acks_late: bool = Field(default=True)
	task_reject_on_worker_lost: bool = Field(default=True)
	worker_prefetch_multiplier: int = Field(default=1)


class ObservabilitySettings(BaseSettings):
	model_config = SettingsConfigDict(extra="ignore")

	sentry_dsn: str = Field(alias="SENTRY_DSN", default="")
	otlp_endpoint: str = Field(alias="OTEL_EXPORTER_OTLP_ENDPOINT", default="http://localhost:4317")
	prometheus_port: int = Field(default=9090)


class EmailSettings(BaseSettings):
	model_config = SettingsConfigDict(extra="ignore")

	smtp_host: str = Field(alias="SMTP_HOST", default="smtp.mailgun.org")
	smtp_port: int = Field(alias="SMTP_PORT", default=587)
	smtp_user: str = Field(alias="SMTP_USER", default="")
	smtp_password: str = Field(alias="SMTP_PASSWORD", default="")
	from_email: str = Field(alias="FROM_EMAIL", default="noreply@gbedu.io")
	use_tls: bool = Field(default=True)


class Settings(BaseSettings):
	model_config = SettingsConfigDict(
		env_file=".env",
		extra="ignore",
		case_sensitive=True,
	)

	environment: str = Field(alias="ENVIRONMENT", default="development")
	log_level: str = Field(alias="LOG_LEVEL", default="INFO")
	frontend_url: str = Field(alias="FRONTEND_URL", default="http://localhost:3000")
	allowed_origins: str = Field(alias="ALLOWED_ORIGINS", default="http://localhost:3000,http://localhost:8000")

	database: DatabaseSettings = Field(default_factory=DatabaseSettings)
	redis: RedisSettings = Field(default_factory=RedisSettings)
	storage: StorageSettings = Field(default_factory=StorageSettings)
	stripe: StripeSettings = Field(default_factory=StripeSettings)
	paystack: PaystackSettings = Field(default_factory=PaystackSettings)
	jwt: JWTSettings = Field(default_factory=JWTSettings)
	ml: MLSettings = Field(default_factory=MLSettings)
	celery: CelerySettings = Field(default_factory=CelerySettings)
	observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
	email: EmailSettings = Field(default_factory=EmailSettings)

	@field_validator("environment")
	@classmethod
	def validate_environment(cls, v: str) -> str:
		allowed = {"development", "staging", "production", "test"}
		assert v in allowed, f"environment must be one of {allowed}"
		return v

	@field_validator("log_level")
	@classmethod
	def validate_log_level(cls, v: str) -> str:
		return v.upper()

	@property
	def is_production(self) -> bool:
		return self.environment == "production"

	@property
	def is_development(self) -> bool:
		return self.environment == "development"

	@property
	def allowed_origins_list(self) -> list[str]:
		return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
	return Settings()
