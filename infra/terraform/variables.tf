variable "project_id" {
  description = "Google Cloud project ID"
  type        = string
}

variable "region" {
  description = "Google Cloud region"
  type        = string
  default     = "asia-southeast1"
}

variable "zone" {
  description = "Google Cloud zone"
  type        = string
  default     = "asia-southeast1-a"

  validation {
    condition     = startswith(var.zone, "${var.region}-")
    error_message = "zone must belong to the configured region."
  }
}

variable "common_name" {
  description = "Name of the storage bucket"
  type        = string
  default     = "gsm-fleet-dispatch"
}

variable "database_deletion_protection" {
  description = "Prevent accidental deletion of the Cloud SQL instance"
  type        = bool
  default     = true
}

variable "database_availability_type" {
  description = "Cloud SQL availability type; use REGIONAL for production"
  type        = string
  default     = "ZONAL"

  validation {
    condition     = contains(["ZONAL", "REGIONAL"], var.database_availability_type)
    error_message = "database_availability_type must be ZONAL or REGIONAL."
  }
}

variable "database_disk_type" {
  description = "Cloud SQL disk type"
  type        = string
  default     = "PD_SSD"

  validation {
    condition     = contains(["PD_SSD", "PD_HDD"], var.database_disk_type)
    error_message = "database_disk_type must be PD_SSD or PD_HDD."
  }
}

variable "database_backup_enabled" {
  description = "Enable automated Cloud SQL backups"
  type        = bool
  default     = true
}

variable "database_point_in_time_recovery" {
  description = "Enable Cloud SQL point-in-time recovery"
  type        = bool
  default     = true
}
