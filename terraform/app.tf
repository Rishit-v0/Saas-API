# Step 1: Build the image using local docker CLI (avoids legacy API bug on Windows)
resource "null_resource" "build_saas_api" {
  triggers = {
    dockerfile_hash   = filemd5("../Dockerfile")
    requirements_hash = filemd5("../requirements.txt")
  }

  provisioner "local-exec" {
    command     = "docker build -t saas-api-tf:latest ../"
    working_dir = path.module # terraform/ directory
  }
}

# Step 2: Reference the image that was just built
resource "docker_image" "saas_api" {
  name         = "saas-api-tf:latest"
  keep_locally = true # Don't try to pull from registry — it's local only

  depends_on = [null_resource.build_saas_api]
}

# Step 3: Run the container
resource "docker_container" "saas_api" {
  image = docker_image.saas_api.image_id
  name  = "saas_api_tf"

  restart = "unless-stopped"

  ports {
    internal = 8000
    external = var.app_port
  }

  env = [
    "DATABASE_URL=postgresql://${var.postgres_user}:${var.postgres_password}@saas_postgres_tf:5432/${var.postgres_db}",
    "DATABASE_USER=${var.postgres_user}",
    "DATABASE_PASSWORD=${var.postgres_password}",
    "DATABASE_HOST=saas_postgres_tf",
    "DATABASE_PORT=5432",
    "DATABASE_NAME=${var.postgres_db}",
    "SECRET_KEY=${var.secret_key}",
    "REDIS_URL=redis://saas_redis_tf:${var.redis_port}/${var.redis_db}",
  ]

  networks_advanced {
    name = docker_network.saas_network.name
  }

  depends_on = [
    docker_container.postgres,
    docker_container.redis,
    docker_image.saas_api
  ]
}