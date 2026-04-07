# network.tf defines the Docker network
# Separating resources into multiple .tf files is best practice
# Terraform merges all .tf files in a directory automatically

resource "docker_network" "saas_network" {
  # resource "type" "name" — name is used to reference this resource elsewhere
  # docker_network.saas_network.name = "saas_network" (the actual Docker network name)
  name = "saas_network"

  # driver = network type
  # bridge = default Docker network type for single-host networking
  # overlay = for Docker Swarm multi-host networking
  driver = "bridge"
}