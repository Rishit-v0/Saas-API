# main.tf = entry point for Terraform configuration
# .tf files use HCL (HashiCorp Configuration Language)
# HCL is designed to be human-readable and writable

terraform {
  # required_version = minimum Terraform version that works with this config
  # ~> 1.0 means >= 1.0.0 and < 2.0.0
  required_version = "~> 1.0"

  required_providers {
    # docker provider lets Terraform manage Docker resources
    # We use Docker provider because it's free and local
    # In production you'd use 'railway', 'aws', or 'google' provider
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

# Configure the Docker provider
# host = where Docker is running
# On Windows with Docker Desktop, this is the named pipe
provider "docker" {
  host = "npipe:////./pipe/docker_engine"
}