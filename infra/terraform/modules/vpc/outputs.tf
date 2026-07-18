output "vpc_id" {
  value       = google_compute_network.vpc_network.id
  description = "VPC ID"
}

output "vpc_name" {
  value       = google_compute_network.vpc_network.name
  description = "VPC Name"
}

output "subnet_ids" {
  value       = { for k, v in google_compute_subnetwork.subnets : k => v.id }
  description = "Subnet IDs"
}
