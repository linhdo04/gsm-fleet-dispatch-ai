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

resource "google_compute_firewall" "allow_http_public" {
  name      = "allow-http-public"
  network   = var.vpc_name
  project   = var.project_id
  direction = "INGRESS"

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }

  target_tags   = ["web-traffic"]
  source_ranges = ["0.0.0.0/0"]
}

resource "google_compute_firewall" "allow-ssh-from-my-ip" {
  name    = "allow-ssh-from-my-ip"
  network = var.vpc_name
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  target_tags   = ["ssh-traffic"]
  source_ranges = [var.my_ip]
}
