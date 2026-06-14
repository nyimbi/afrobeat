provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# ── Production audio bucket ────────────────────────────────────────────────────

resource "cloudflare_r2_bucket" "gbedu_audio" {
  account_id = var.cloudflare_account_id
  name       = "gbedu-audio"
  location   = "WEUR"
}

resource "cloudflare_r2_bucket_cors" "gbedu_audio_cors" {
  account_id = var.cloudflare_account_id
  bucket_name = cloudflare_r2_bucket.gbedu_audio.name

  rules = [
    {
      allowed_origins = [var.frontend_url, "https://www.gbedu.io"]
      allowed_methods = ["GET", "HEAD", "PUT", "POST", "DELETE"]
      allowed_headers = [
        "Content-Type",
        "Content-Length",
        "Authorization",
        "x-amz-content-sha256",
        "x-amz-date",
        "x-amz-security-token",
      ]
      expose_headers  = ["ETag", "Content-Length", "Content-Type"]
      max_age_seconds = 3600
    },
  ]
}

# ── Staging audio bucket ───────────────────────────────────────────────────────

resource "cloudflare_r2_bucket" "gbedu_audio_staging" {
  account_id = var.cloudflare_account_id
  name       = "gbedu-audio-staging"
  location   = "WEUR"
}

resource "cloudflare_r2_bucket_cors" "gbedu_audio_staging_cors" {
  account_id = var.cloudflare_account_id
  bucket_name = cloudflare_r2_bucket.gbedu_audio_staging.name

  rules = [
    {
      allowed_origins = [
        "https://staging.gbedu.io",
        "http://localhost:3000",
        "http://localhost:8000",
      ]
      allowed_methods = ["GET", "HEAD", "PUT", "POST", "DELETE"]
      allowed_headers = [
        "Content-Type",
        "Content-Length",
        "Authorization",
        "x-amz-content-sha256",
        "x-amz-date",
        "x-amz-security-token",
      ]
      expose_headers  = ["ETag", "Content-Length", "Content-Type"]
      max_age_seconds = 3600
    },
  ]
}

# ── Outputs ────────────────────────────────────────────────────────────────────

output "production_bucket_name" {
  description = "Name of the production R2 audio bucket."
  value       = cloudflare_r2_bucket.gbedu_audio.name
}

output "production_bucket_public_url" {
  description = "Public S3-compatible endpoint for the production bucket."
  value       = "https://${var.cloudflare_account_id}.r2.cloudflarestorage.com/${cloudflare_r2_bucket.gbedu_audio.name}"
}

output "staging_bucket_name" {
  description = "Name of the staging R2 audio bucket."
  value       = cloudflare_r2_bucket.gbedu_audio_staging.name
}

output "staging_bucket_public_url" {
  description = "Public S3-compatible endpoint for the staging bucket."
  value       = "https://${var.cloudflare_account_id}.r2.cloudflarestorage.com/${cloudflare_r2_bucket.gbedu_audio_staging.name}"
}
