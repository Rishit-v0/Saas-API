output "api_url" {
  description = "URL to access the Saas API"
  value       = "http://localhost:${var.app_port}"
}

output "api_docs_url" {
  description = "Swagger UI URL"
  value       = "http://localhost:${var.app_port}/docs"
}

output "postgres_port" {
  description = "PostgreSQL port on host machine"
  value       = 5432
}

output "redis_port" {
  description = "Redis port on host machine"
  value       = 6379
}