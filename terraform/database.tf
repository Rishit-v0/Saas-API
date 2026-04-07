# Pull the postgres image first
resource "docker_image" "postgres" {
  # name = Docker image to pull
  # Using specific version tag — never use 'latest' in Terraform
  # 'latest' is unpredictable — version tag is reproducible
  name = "postgres:15-alpine"

  # keep_locally = don't delete image when terraform destroy is run
  # Useful to keep for faster future rebuilds
  keep_locally = false
}

resource "docker_container" "postgres" {
  # image = reference to the docker_image resource above
  # Terraform knows to create the image BEFORE the container
  # This is dependency resolution — Terraform figures out order automatically
  image = docker_image.postgres.image_id
  name  = "saas_postgres_tf" # _tf suffix to distinguish from docker-compose containers

  # restart = what to do when container stops
  # "unless-stopped" = always restart unless manually stopped
  restart = "unless-stopped"

  # ports block = port mapping (host:container)
  ports {
    internal = 5432 # port inside container
    external = 5432 # port on your machine 
  }

  # env = environment variables
  # Note: var.postgres_password references the variable we defined
  # Terraform substitutes the actual value at apply time
  env = [
    "POSTGRES_DB=${var.postgres_db}",
    "POSTGRES_USER=${var.postgres_user}",
    "POSTGRES_PASSWORD=${var.postgres_password}",
  ]

  # networks_advanced = connect to our custom network
  # This is how containers find each other by name
  networks_advanced {
    name = docker_network.saas_network.name
  }

  # volumes block = persistent storage
  # Without this, all data is lost when container stops
  volumes {
    volume_name    = docker_volume.postgres_data.name
    container_path = "/var/lib/postgresql/data"
  }

  # healthcheck = Terraform waits for this before marking container healthy
  healthcheck {
    test         = ["CMD-SHELL", "pg_isready -U ${var.postgres_user}"]
    interval     = "10s"
    timeout      = "5s"
    retries      = 5
    start_period = "10s"
  }
}

# Persistent volume for PostgreSQL data
resource "docker_volume" "postgres_data" {
  name = "saas_postgres_tf_data"
}