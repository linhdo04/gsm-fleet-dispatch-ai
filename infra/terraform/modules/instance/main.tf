resource "google_compute_disk" "data" {
  count = var.data_disk_size > 0 ? 1 : 0

  name    = "${var.instance_name}-data"
  type    = var.data_disk_type
  zone    = var.zone
  project = var.project_id
  size    = var.data_disk_size

  lifecycle {
    prevent_destroy = false
  }
}

resource "google_compute_instance" "vm_instance" {
  name         = var.instance_name
  machine_type = var.machine_type
  zone         = var.zone
  project      = var.project_id

  allow_stopping_for_update = true
  deletion_protection       = false

  tags = var.network_tags

  boot_disk {
    initialize_params {
      image = var.boot_image
      size  = var.boot_disk_size
      type  = "pd-standard"
    }
  }

  network_interface {
    subnetwork = var.subnet_id

    dynamic "access_config" {
      for_each = var.enable_public_ip ? [1] : []
      content {
      }
    }
  }

  service_account {
    scopes = ["logging-write", "monitoring-write"]
  }

  metadata = merge(
    {
      enable-oslogin         = "TRUE"
      block-project-ssh-keys = "TRUE"
      serial-port-enable     = "FALSE"
    },
    var.startup_script != "" ? { "startup-script" = var.startup_script } : {}
  )

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

}

resource "google_compute_attached_disk" "data" {
  count = var.data_disk_size > 0 ? 1 : 0

  disk        = google_compute_disk.data[0].id
  instance    = google_compute_instance.vm_instance.id
  device_name = "observability-data"
  mode        = "READ_WRITE"
  project     = var.project_id
  zone        = var.zone
}
