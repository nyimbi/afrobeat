variable "cloudflare_account_id" {
  description = "Cloudflare account ID that owns the R2 buckets."
  type        = string
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token with R2 write permissions."
  type        = string
  sensitive   = true
}

variable "environment" {
  description = "Deployment environment: production | staging | development."
  type        = string

  validation {
    condition     = contains(["production", "staging", "development"], var.environment)
    error_message = "environment must be one of: production, staging, development."
  }
}

variable "frontend_url" {
  description = "Public URL of the Gbẹdu frontend (used for CORS allow-origin)."
  type        = string
  default     = "https://gbedu.io"
}
