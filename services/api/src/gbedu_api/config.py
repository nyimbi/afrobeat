from __future__ import annotations

from gbedu_core.config import Settings, get_settings as _get_settings

# Re-export everything from core — API-specific overrides are additive
__all__ = ["Settings", "get_settings", "API_VERSION"]

API_VERSION = "0.1.0"

# API-specific rate limit constants — these live here so the core lib
# stays unaware of HTTP-layer concerns.
RATE_LIMIT_FREE = "3/day"
RATE_LIMIT_CREATOR = "1000/day"
RATE_LIMIT_PRO = "10000/day"
RATE_LIMIT_LABEL = "100000/day"

# Auth rate limits — tuned to block abuse while allowing legitimate bursts.
# Register: tight (prevents bulk account farming per IP)
# Login: moderate sliding window (brute-force protection without locking out CDN IPs)
# Refresh: generous (tokens expire naturally; clients need headroom)
# Logout: unlimited (always safe to log out)
RATE_LIMIT_REGISTER    = "3/hour"   # tightened per FMEA S05
RATE_LIMIT_LOGIN       = "20/minute"
RATE_LIMIT_REFRESH     = "120/minute"
RATE_LIMIT_AUTH        = "20/minute"   # generic fallback for other auth endpoints

MAX_UPLOAD_SIZE_MB = 10
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# Presigned URL lifetime for audio downloads
PRESIGNED_URL_EXPIRES_SECONDS = 3600


def get_settings() -> Settings:
	return _get_settings()
