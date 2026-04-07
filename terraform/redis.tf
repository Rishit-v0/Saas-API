resource "docker_image" "redis" {
  name = "redis:7-alpine"

  keep_locally = false
}

resource "docker_container" "redis" {
  image = docker_image.redis.image_id
  name  = "saas_redis_tf"

  restart = "unless-stopped"

  command = ["redis-server", "--appendonly", "yes"]

  ports {
    internal = 6379
    external = 6379
  }

  networks_advanced {
    name = docker_network.saas_network.name
  }

  volumes {
    volume_name    = docker_volume.redis_data.name
    container_path = "/data"
  }
}

resource "docker_volume" "redis_data" {
  name = "saas_redis_tf_data"
}