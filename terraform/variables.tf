variable "postgres_password" {
  description = "The password for the PostgreSQL database."
  type        = string
  sensitive   = true
}

variable "postgres_user" {
  description = "The username for the PostgreSQL database."
  type        = string
  default     = "rishit"
  sensitive   = true
}

variable "postgres_db" {
  description = "The name of the PostgreSQL database."
  type        = string
  default     = "saas_db"
  sensitive   = true
}

variable "postgres_host" {
  description = "The hostname of the PostgreSQL database."
  type        = string
  default     = "saas_postgres"
  sensitive   = true
}

variable "postgres_port" {
  description = "The port number for the PostgreSQL database."
  type        = number
  default     = 5432
}

variable "secret_key" {
  description = "The secret key for the application."
  type        = string
  sensitive   = true
}

variable "app_port" {
  description = "The port number for the application to run on."
  type        = number
  default     = 8000
}

variable "redis_host" {
  description = "The hostname of the Redis server."
  type        = string
  default     = "redis"
}

variable "redis_port" {
  description = "The port number for the Redis server."
  type        = number
  default     = 6379
}

variable "redis_db" {
  description = "The database number for the Redis server."
  type        = number
  default     = 0
}