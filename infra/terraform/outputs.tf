output "web_server_public_ip" {
  value       = module.instance.public_ip
  description = "Public IP address of the web server instance"
}

output "postgres_connection_name" {
  value       = module.database.postgres_connection_name
  description = "Cloud SQL connection name for connectors and the Auth Proxy"
}

output "bucket_name" {
  description = "Name of the Cloud Storage bucket"
  value       = module.bucket.name
}

output "bucket_url" {
  description = "Cloud Storage bucket URL"
  value       = module.bucket.url
}
