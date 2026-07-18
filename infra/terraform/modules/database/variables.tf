variable "project_id" {
  description = "Google Cloud project ID"
  type        = string
}

variable "region" {
  description = "Google Cloud region"
  type        = string
  default     = "asia-southeast1"
}

variable "common_name" {
  description = "Name of the storage bucket"
  type        = string
  default     = "gsm-fleet-dispatch"
}

variable "vpc_id" {
  description = "ID of the VPC"
  type        = string
}

variable "deletion_protection" {
  description = "Prevent accidental deletion of the Cloud SQL instance"
  type        = bool
  default     = true
}

variable "availability_type" {
  description = "Cloud SQL availability type"
  type        = string
  default     = "ZONAL"

  validation {
    condition     = contains(["ZONAL", "REGIONAL"], var.availability_type)
    error_message = "availability_type must be ZONAL or REGIONAL."
  }
}

variable "disk_type" {
  description = "Cloud SQL disk type"
  type        = string
  default     = "PD_SSD"

  validation {
    condition     = contains(["PD_SSD", "PD_HDD"], var.disk_type)
    error_message = "disk_type must be PD_SSD or PD_HDD."
  }
}

variable "backup_enabled" {
  description = "Enable automated Cloud SQL backups"
  type        = bool
  default     = true
}

variable "point_in_time_recovery" {
  description = "Enable Cloud SQL point-in-time recovery"
  type        = bool
  default     = true
}
