terraform {
  required_version = ">= 1.6"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = ">= 4.0"
    }
  }

  # Remote state — swap for your preferred backend (S3, Terraform Cloud, etc.)
  # backend "s3" {
  #   bucket = "gbedu-tfstate"
  #   key    = "infra/terraform.tfstate"
  #   region = "auto"
  # }
}
