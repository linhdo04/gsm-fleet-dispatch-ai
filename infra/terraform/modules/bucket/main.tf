resource "google_storage_bucket" "this" {
  project  = var.project_id
  name     = var.name
  location = var.location

  force_destroy               = var.force_destroy
  public_access_prevention    = "enforced"
  uniform_bucket_level_access = true

  versioning {
    enabled = var.versioning_enabled
  }

  dynamic "lifecycle_rule" {
    for_each = var.noncurrent_version_retention_days == null ? [] : [var.noncurrent_version_retention_days]

    content {
      action {
        type = "Delete"
      }

      condition {
        days_since_noncurrent_time = lifecycle_rule.value
      }
    }
  }

  labels = var.labels
}
