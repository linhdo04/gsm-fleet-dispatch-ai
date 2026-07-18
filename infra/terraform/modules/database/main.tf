resource "google_project_service" "sql_admin" {
  project            = var.project_id
  service            = "sqladmin.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "service_networking" {
  project            = var.project_id
  service            = "servicenetworking.googleapis.com"
  disable_on_destroy = false
}

resource "google_compute_global_address" "private_service_access" {
  name          = "${var.common_name}-private-service-access"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = var.vpc_id
}

resource "google_service_networking_connection" "private_service_access" {
  network                 = var.vpc_id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_access.name]

  depends_on = [google_project_service.service_networking]
}

resource "google_sql_database_instance" "postgres" {
  name                = "${var.common_name}-postgres"
  project             = var.project_id
  region              = var.region
  database_version    = "POSTGRES_15"
  deletion_protection = var.deletion_protection

  settings {
    tier              = "db-f1-micro"
    edition           = "ENTERPRISE"
    availability_type = var.availability_type

    disk_type       = var.disk_type
    disk_size       = 10
    disk_autoresize = true

    backup_configuration {
      enabled                        = var.backup_enabled
      point_in_time_recovery_enabled = var.point_in_time_recovery
    }

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = var.vpc_id
      enable_private_path_for_google_cloud_services = false
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }
  }

  depends_on = [
    google_project_service.sql_admin,
    google_service_networking_connection.private_service_access,
  ]
}

resource "google_sql_database" "app" {
  name     = "fleet_dispatch"
  project  = var.project_id
  instance = google_sql_database_instance.postgres.name
}
