provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

module "network" {
  source       = "./modules/vpc"
  project_id   = var.project_id
  network_name = "${var.common_name}-vpc"

  subnets = [
    {
      name          = "${var.common_name}-subnet"
      ip_cidr_range = "10.10.1.0/24"
      region        = var.region
    }
  ]
}

module "instance" {
  source         = "./modules/instance"
  project_id     = var.project_id
  instance_name  = "${var.common_name}-server"
  zone           = var.zone
  machine_type   = "e2-standard-2"
  boot_disk_size = 20

  subnet_id = module.network.subnet_ids["${var.common_name}-subnet"]

  network_tags     = ["web-traffic", "ssh-traffic"]
  enable_public_ip = false
  data_disk_size   = 100
}

module "database" {
  source                 = "./modules/database"
  project_id             = var.project_id
  region                 = var.region
  common_name            = var.common_name
  vpc_id                 = module.network.vpc_id
  deletion_protection    = var.database_deletion_protection
  availability_type      = var.database_availability_type
  disk_type              = var.database_disk_type
  backup_enabled         = var.database_backup_enabled
  point_in_time_recovery = var.database_point_in_time_recovery
}

module "firewall" {
  source     = "./modules/firewall"
  project_id = var.project_id
  vpc_name   = module.network.vpc_name
}

module "registry" {
  source     = "./modules/registry"
  project_id = var.project_id
  region     = var.region
}

module "bucket" {
  source     = "./modules/bucket"
  project_id = var.project_id
  name       = "${var.project_id}-${var.common_name}"
  location   = var.region
}
