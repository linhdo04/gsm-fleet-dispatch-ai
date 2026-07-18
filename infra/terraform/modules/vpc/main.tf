resource "google_compute_network" "vpc_network" {
  name                    = var.network_name
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnets" {
  for_each = { for subnet in var.subnets : subnet.name => subnet }

  name          = each.value.name
  ip_cidr_range = each.value.ip_cidr_range
  region        = each.value.region
  network       = google_compute_network.vpc_network.id
  project       = var.project_id

  private_ip_google_access = true
}

resource "google_compute_firewall" "allow_internal_icmp" {
  name    = "${var.network_name}-allow-internal-icmp"
  network = google_compute_network.vpc_network.name
  project = var.project_id

  allow {
    protocol = "icmp"
  }
  source_ranges = [for subnet in var.subnets : subnet.ip_cidr_range]
  priority      = 1000
}

resource "google_compute_router" "nat" {
  for_each = toset(distinct([for subnet in var.subnets : subnet.region]))

  name    = "${var.network_name}-nat-${each.value}"
  network = google_compute_network.vpc_network.id
  region  = each.value
  project = var.project_id
}

resource "google_compute_router_nat" "nat" {
  for_each = google_compute_router.nat

  name                               = "${var.network_name}-nat-${each.key}"
  router                             = each.value.name
  region                             = each.key
  project                            = var.project_id
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
