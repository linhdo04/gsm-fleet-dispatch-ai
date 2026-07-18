output "web_server_public_ip" {
  value       = module.instance.public_ip
  description = "Public IP address of the web server instance"
}

output "postgres_connection_name" {
  value       = module.database.postgres_connection_name
  description = "Cloud SQL connection name for connectors and the Auth Proxy"
}
