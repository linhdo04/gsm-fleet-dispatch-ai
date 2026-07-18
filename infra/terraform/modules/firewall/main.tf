resource "google_compute_firewall" "allow_ssh_iap" {
  name    = "allow-ssh-from-iap"
  network = var.vpc_name
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  target_tags   = ["ssh-traffic"]
  source_ranges = ["35.235.240.0/20"]
}
