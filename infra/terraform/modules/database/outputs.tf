output "postgres_connection_name" {
  description = "Cloud SQL connection name for connectors and the Auth Proxy"
  value       = google_sql_database_instance.postgres.connection_name
}
