# terraform {
#   backend "local" {
#     path = "terraform.tfstate"
#   }
# }

terraform {
  backend "consul" {
    address = "172.16.0.131:8500"
    scheme  = "http"
    path    = "terraform/homelab"
    # access_token = ""
    datacenter = "homelab"
    gzip = true
  }
}