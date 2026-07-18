output "instance_id" {
  value       = google_compute_instance.vm_instance.id
  description = "Instance ID"
}

output "private_ip" {
  value       = google_compute_instance.vm_instance.network_interface[0].network_ip
  description = "Private IP address of the instance"
}

output "public_ip" {
  value       = length(google_compute_instance.vm_instance.network_interface[0].access_config) > 0 ? google_compute_instance.vm_instance.network_interface[0].access_config[0].nat_ip : null
  description = "Public IP address of the instance"
}

output "data_disk_id" {
  description = "ID of the attached persistent data disk"
  value       = try(google_compute_disk.data[0].id, null)
}
