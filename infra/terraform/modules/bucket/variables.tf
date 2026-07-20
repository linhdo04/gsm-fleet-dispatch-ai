variable "project_id" {
  description = "Google Cloud project ID"
  type        = string
}

variable "name" {
  description = "Globally unique Cloud Storage bucket name"
  type        = string

  validation {
    condition     = length(var.name) >= 3 && length(var.name) <= 63 && can(regex("^[a-z0-9][a-z0-9._-]*[a-z0-9]$", var.name))
    error_message = "name must be 3-63 characters and use only lowercase letters, numbers, dots, underscores, or hyphens."
  }
}

variable "location" {
  description = "Cloud Storage bucket location"
  type        = string
  default     = "asia-southeast1"
}

variable "force_destroy" {
  description = "Allow Terraform to delete the bucket when it contains objects"
  type        = bool
  default     = false
}

variable "versioning_enabled" {
  description = "Enable object versioning"
  type        = bool
  default     = true
}

variable "noncurrent_version_retention_days" {
  description = "Delete noncurrent object versions after this many days; null disables the rule"
  type        = number
  default     = 30

  validation {
    condition     = var.noncurrent_version_retention_days == null || var.noncurrent_version_retention_days > 0
    error_message = "noncurrent_version_retention_days must be null or greater than zero."
  }
}

variable "labels" {
  description = "Labels to apply to the bucket"
  type        = map(string)
  default     = {}
}
