resource "google_artifact_registry_repository" "docker_repo" {
  project       = var.project_id
  location      = var.region
  repository_id = "fleet-dispatch-images"
  description   = "Docker repository for Fleet Dispatch AI applications"
  format        = "DOCKER"

  cleanup_policies {
    id     = "keep-latest-versions"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }

  cleanup_policies {
    id     = "delete-old-images"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 days
    }
  }
}
